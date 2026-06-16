"""
ScoreStream — FastAPI serving layer
Serves live scores, player stats, and standings from PostgreSQL with Redis caching.
"""

import json
import os
import re
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
import psycopg2.extras
import redis
import anthropic

from fastapi import FastAPI, HTTPException, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import TopicPartition

from datetime import datetime, timedelta, timezone

from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

import asyncio
import redis.asyncio as aioredis

# ── Config ───────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "dbname":   os.getenv("DB_NAME", "scorestream"),
    "user":     os.getenv("DB_USER", "admin"),
    "password": os.getenv("DB_PASSWORD", "password"),
    "port":     int(os.getenv("DB_PORT", 5432)),
}

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))

cache = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

ALLOWED = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
class ConnectionManager:
    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active.append(websocket)
        print(f"[ws] Client connected — {len(self.active)} total")

    def disconnect(self, websocket: WebSocket):
        self.active.remove(websocket)
        print(f"[ws] Client disconnected — {len(self.active)} total")

    async def broadcast(self, message:str):
        disconnected = []

        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)

        for ws in disconnected:
            self.active.remove(ws)

manager = ConnectionManager()

anthropic_client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DB_SCHEMA = """
These are the database tables for the ScoreStream application:

games (
    league          VARCHAR DEFAULT 'epl',
    game_id         VARCHAR PRIMARY KEY,
    home_team       VARCHAR NOT NULL,
    home_team_name  VARCHAR NOT NULL,
    home_id         VARCHAR NOT NULL,
    away_team       VARCHAR NOT NULL,
    away_team_name  VARCHAR NOT NULL,
    away_id         VARCHAR NOT NULL,
    home_score      INT DEFAULT 0,
    away_score      INT DEFAULT 0,
    period          VARCHAR,
    clock           VARCHAR,
    status          VARCHAR NOT NULL,  -- STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_FULL_TIME, STATUS_ABANDONED
    status_detail   VARCHAR,
    start_time      TIMESTAMP,
    matchday        INTEGER DEFAULT 0,
    last_updated    TIMESTAMP DEFAULT NOW()
)

goals (
    id              SERIAL PRIMARY KEY,
    game_id         VARCHAR REFERENCES games(game_id) ON DELETE CASCADE,
    league          VARCHAR DEFAULT 'epl',
    player_id       VARCHAR NOT NULL,
    player_name     VARCHAR NOT NULL,
    team_id         VARCHAR NOT NULL,
    minute          VARCHAR,
    seconds         INT,
    goal_type       VARCHAR,  -- e.g., "Goal, Goal - Volley, Goal - Header, Penalty - Scored, Goal - Free-kick"
    own_goal        BOOLEAN DEFAULT FALSE,
    penalty_goal    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),
)

standings (
    team_id         VARCHAR NOT NULL,
    league          VARCHAR NOT NULL DEFAULT 'epl',
    team_name       VARCHAR NOT NULL,
    wins            INT DEFAULT 0,
    losses          INT DEFAULT 0,
    draws           INT DEFAULT 0,
    points          INT DEFAULT 0,
    goals_for       INT DEFAULT 0,
    goals_against   INT DEFAULT 0,
    goal_diff       INT DEFAULT 0,
    matches_played  INT DEFAULT 0,
    rank            INT DEFAULT 0,
    deductions      INT DEFAULT 0,
    last_updated    TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (team_id, league)
)

season_stats (
    player_id    VARCHAR,
    player_name  VARCHAR,
    team_id      VARCHAR,
    team_name    VARCHAR,
    league       VARCHAR,        -- 'epl', 'laliga', etc.
    season       INTEGER,        -- start year e.g. 2025 for 2025/26
    goals        INTEGER,        -- total goals scored in the season
    assists      INTEGER,
    penalties    INTEGER,        -- penalty goals included in total
    last_updated TIMESTAMP,
    PRIMARY KEY (player_id, league, season)
)

NOTE: season_stats contains aggregated totals from football-data.org.
Use this table for questions like 'who is the top scorer this season'
or 'how many goals has Haaland scored'. Do NOT use the goals table
for season total queries — it only contains recent match events from ESPN.

Note on leagues:
- 'worldcup' refers to the 2026 FIFA World Cup
- World Cup games follow the same schema as club leagues
- home_team and away_team are national team abbreviations (e.g. 'ENG', 'BRA', 'ARG')
- home_team_name and away_team_name are full country names (e.g. 'England', 'Brazil')

Example queries:

-- Who scored in Arsenal's last game?
SELECT 
    gl.player_name,
    gl.minute,
    gl.goal_type,
    gl.own_goal,
    gl.penalty_goal,
    CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
        ELSE 'Unknown'
    END AS scored_for,
    gm.home_team_name,
    gm.away_team_name,
    gm.home_score,
    gm.away_score,
    gm.start_time,
    gm.status
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE (gm.home_team_name ILIKE '%arsenal%' OR gm.away_team_name ILIKE '%arsenal%')
AND gm.game_id = (
    SELECT game_id FROM games
    WHERE (home_team_name ILIKE '%arsenal%' OR away_team_name ILIKE '%arsenal%')
    AND status NOT IN (
        'STATUS_SCHEDULED', 
        'STATUS_IN_PROGRESS', 
        'STATUS_HALFTIME',
        'STATUS_FIRST_HALF',
        'STATUS_SECOND_HALF'
    )
    ORDER BY start_time DESC
    LIMIT 1
)
ORDER BY gl.seconds ASC;

-- What was the score in Arsenal's last game?
SELECT home_team_name, away_team_name, home_score, away_score, start_time, status_detail
FROM games
WHERE (home_team_name ILIKE '%arsenal%' OR away_team_name ILIKE '%arsenal%')
AND status IN ('STATUS_FULL_TIME', 'STATUS_ABANDONED')
ORDER BY start_time DESC
LIMIT 1;

-- Who is the top scorer in the Premier League?
SELECT player_name, COUNT(*) as goals,
       SUM(CASE WHEN own_goal THEN 1 ELSE 0 END) as own_goals
FROM goals
WHERE league = 'epl' AND own_goal = false
GROUP BY player_name
ORDER BY goals DESC
LIMIT 10;

-- What is the goal difference for the bottom 3 teams in the Bundesliga?
SELECT team_name, goal_diff, points, rank
FROM standings
WHERE league = 'bundesliga'
ORDER BY goal_diff ASC
LIMIT 3;

-- Show me goal difference across all Premier League teams
SELECT team_name, goal_diff
FROM standings
WHERE league = 'epl'
ORDER BY goal_diff DESC;

-- Which teams have the best goal difference in La Liga?
SELECT team_name, goal_diff, points, rank
FROM standings
WHERE league = 'laliga'
ORDER BY goal_diff DESC
LIMIT 5;

-- How many goals were scored today?
SELECT COUNT(*) as total_goals, g.league
FROM goals g
JOIN games gm ON g.game_id = gm.game_id
WHERE DATE(gm.start_time) = CURRENT_DATE
AND g.own_goal = false
GROUP BY g.league;

-- Show me PSG's form over their last 5 games
SELECT 
    CASE 
        WHEN gm.home_team_name ILIKE '%Paris Saint-Germain%' THEN gm.away_team_name
        WHEN gm.away_team_name ILIKE '%Paris Saint-Germain%' THEN gm.home_team_name
    END AS opponent,                          -- ← use opponent as x-axis label
    TO_CHAR(gm.start_time, 'Mon DD') AS match_date,  -- ← formatted date as readable label
    CASE
        WHEN gm.home_team_name ILIKE '%Paris Saint-Germain%' THEN
            CASE WHEN gm.home_score > gm.away_score THEN 3
                 WHEN gm.home_score = gm.away_score THEN 1
                 ELSE 0 END
        WHEN gm.away_team_name ILIKE '%Paris Saint-Germain%' THEN
            CASE WHEN gm.away_score > gm.home_score THEN 3
                 WHEN gm.away_score = gm.home_score THEN 1
                 ELSE 0 END
    END AS points,
    gm.start_time
FROM games gm
WHERE (gm.home_team_name ILIKE '%Paris Saint-Germain%' 
    OR gm.away_team_name ILIKE '%Paris Saint-Germain%')
AND gm.status NOT IN ('STATUS_SCHEDULED', 'STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF')
ORDER BY gm.start_time ASC
LIMIT 5;

-- Who scored in Arsenal's last game?
SELECT 
    g.player_name,
    g.minute,
    g.goal_type,
    g.own_goal,
    g.penalty_goal,
    CASE 
        WHEN g.team_id = gm.home_id THEN gm.home_team_name
        WHEN g.team_id = gm.away_id THEN gm.away_team_name
        ELSE 'Unknown'
    END AS scored_for,
    gm.home_team_name,
    gm.away_team_name,
    gm.home_score,
    gm.away_score,
    gm.start_time
FROM goals g
JOIN games gm ON g.game_id = gm.game_id
WHERE (gm.home_team_name ILIKE '%arsenal%' OR gm.away_team_name ILIKE '%arsenal%')
AND gm.status IN ('STATUS_FULL_TIME', 'STATUS_ABANDONED')
AND gm.game_id = (
    SELECT game_id FROM games
    WHERE (home_team_name ILIKE '%arsenal%' OR away_team_name ILIKE '%arsenal%')
    AND status IN ('STATUS_FULL_TIME', 'STATUS_ABANDONED')
    ORDER BY start_time DESC
    LIMIT 1
)
ORDER BY g.seconds ASC;

-- What happened in Burnley's last game? / Tell me about Arsenal's last game
SELECT 
    gm.home_team_name,
    gm.away_team_name,
    gm.home_score,
    gm.away_score,
    gm.start_time,
    gm.status,
    gl.player_name,
    gl.minute,
    gl.goal_type,
    gl.own_goal,
    gl.penalty_goal,
    CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
        ELSE 'Unknown'
    END AS scored_for
FROM games gm
LEFT JOIN goals gl ON gm.game_id = gl.game_id
WHERE (gm.home_team_name ILIKE '%burnley%' OR gm.away_team_name ILIKE '%burnley%')
AND gm.game_id = (
    SELECT game_id FROM games
    WHERE (home_team_name ILIKE '%burnley%' OR away_team_name ILIKE '%burnley%')
    AND status NOT IN (
        'STATUS_SCHEDULED',
        'STATUS_IN_PROGRESS', 
        'STATUS_HALFTIME',
        'STATUS_FIRST_HALF',
        'STATUS_SECOND_HALF'
    )
    ORDER BY start_time DESC
    LIMIT 1
)
ORDER BY gl.seconds ASC;

-- Who is the top scorer in Ligue 1?
SELECT 
    gl.player_name,
    COUNT(*) as goals,
    MAX(CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END) as team_name
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'ligue1'
AND gl.own_goal = false
GROUP BY gl.player_name
ORDER BY goals DESC
LIMIT 1;

-- Who are the top 10 scorers in the Premier League?
SELECT 
    gl.player_name,
    COUNT(*) as goals,
    MAX(CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END) as team_name
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'epl'
AND gl.own_goal = false
GROUP BY gl.player_name
ORDER BY goals DESC
LIMIT 10;

-- Who is the top scorer in the Bundesliga this season?
SELECT player_name, team_name, goals, assists, penalties
FROM season_stats
WHERE league = 'bundesliga' AND season = 2025
ORDER BY goals DESC
LIMIT 10;

-- Who has the most assists in the Premier League?
SELECT player_name, team_name, assists
FROM season_stats
WHERE league = 'epl' AND season = 2025
ORDER BY assists DESC
LIMIT 10;

-- Show me a player's full stats
SELECT player_name, team_name, goals, assists, penalties
FROM season_stats
WHERE player_name ILIKE '%Mbappe%' AND season = 2025;

-- Show me Barcelona's last game (NOT Espanyol)
SELECT gm.home_team_name, gm.away_team_name, gm.home_score, gm.away_score, gm.start_time
FROM games gm
WHERE (
    (gm.home_team_name ILIKE '%Barcelona%' AND gm.home_team_name NOT ILIKE '%Espanyol%')
    OR
    (gm.away_team_name ILIKE '%Barcelona%' AND gm.away_team_name NOT ILIKE '%Espanyol%')
)
AND gm.status NOT IN ('STATUS_SCHEDULED', 'STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF')
ORDER BY gm.start_time DESC
LIMIT 1;

-- Which World Cup games are today?
SELECT home_team_name, away_team_name, home_score, away_score, status, start_time
FROM games
WHERE league = 'worldcup'
AND DATE(start_time) = CURRENT_DATE
ORDER BY start_time ASC;

-- Who has scored at the World Cup?
SELECT 
    gl.player_name,
    COUNT(*) as goals,
    MAX(CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END) as country
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'worldcup'
AND gl.own_goal = false
GROUP BY gl.player_name
ORDER BY goals DESC
LIMIT 10;

-- What were the results in the World Cup group stage?
SELECT home_team_name, away_team_name, home_score, away_score, start_time
FROM games
WHERE league = 'worldcup'
AND status IN ('STATUS_FULL_TIME', 'STATUS_FINAL')
ORDER BY start_time ASC;
"""

TEAM_ALIASES = """
Common team name aliases — always expand these to their full ESPN name in queries:

PSG, Paris SG → Paris Saint-Germain
Man United, Man Utd, MUFC → Manchester United
Man City, MCFC → Manchester City
Spurs → Tottenham Hotspur
Inter, Inter Milan → Internazionale
Inter Miami → Inter Miami
Barca, FCB, Varca, Varcelona → Barcelona
Real → Real Madrid
Atletico, Atletico Madrid → Atlético Madrid
Wolves → Wolverhampton Wanderers
West Ham → West Ham United
Newcastle → Newcastle United
Nottm Forest, Nott'm Forest, Forest → Nottingham Forest
Brighton → Brighton & Hove Albion
Leicester → Leicester City
Bournemouth → AFC Bournemouth
Wolves → Wolverhampton Wanderers
Leverkusen → Bayer Leverkusen
Dortmund, BVB → Borussia Dortmund
Gladbach → Borussia Mönchengladbach
Frankfurt → Eintracht Frankfurt
Schalke → FC Schalke 04
Freiburg → SC Freiburg
Juve → Juventus
Roma → AS Roma
Lazio → Lazio
Napoli → Napoli
Milan, AC Milan → AC Milan
Sociedad → Real Sociedad
Betis → Real Betis
Villarreal → Villarreal
Sevilla → Sevilla
Lyon → Lyon
Marseille → Marseille
Monaco → AS Monaco
Lille → Lille
Rennes → Stade Rennais
"""

WORLD_CUP_ALIASES = """
World Cup country name aliases:
USA, United States → United States
England → England (not Great Britain)
Korea → South Korea
Iran → Iran
Ivory Coast → Ivory Coast
Bosnia → Bosnia-Herzegovina
Czech Republic → Czechia
Turkey → Türkiye
Curacao → Curaçao
Congo → DR Congo
"""

ALIAS_MAP = {
    "psg":              "Paris Saint-Germain",
    "man united":       "Manchester United",
    "man utd":          "Manchester United",
    "man city":         "Manchester City",
    "spurs":            "Tottenham Hotspur",
    "inter":            "Internazionale",
    "barca":            "Barcelona",
    "real madrid":      "Real Madrid",
    "atletico":         "Atlético Madrid",
    "atleti":           "Atlético Madrid",
    "wolves":           "Wolverhampton Wanderers",
    "west ham":         "West Ham United",
    "newcastle":        "Newcastle United",
    "brighton":         "Brighton & Hove Albion",
    "leicester":        "Leicester City",
    "forest":           "Nottingham Forest",
    "wolves":           "Wolverhampton Wanderers",
    "bournemoth":       "AFC Bournemouth",
    "leverkusen":       "Bayer Leverkusen",
    "dortmund":         "Borussia Dortmund",
    "bvb":              "Borussia Dortmund",
    "juve":             "Juventus",
    "juventus":         "Juventus",
    "roma":             "AS Roma",
    "milan":            "AC Milan",
    "lyon":             "Lyon",
    "marseille":        "Marseille",
    "lille":            "Lille",
    "monaco":           "AS Monaco",
    "alaves":           "Alavés",
    "usa":              "United States",
    "united states":    "United States",
    "america":          "United States",
    "england":          "England",
    "three lions":      "England",
    "brazil":           "Brazil",
    "seleção":          "Brazil",
    "argentina":        "Argentina",
    "france":           "France",
    "les bleus":        "France",
    "germany":          "Germany",
    "die mannschaft":   "Germany",
    "spain":            "Spain",
    "la roja":          "Spain",
    "portugal":         "Portugal",
    "netherlands":      "Netherlands",
    "holland":          "Netherlands",
    "morocco":          "Morocco",
    "japan":            "Japan",
    "south korea":      "South Korea",
    "korea":            "South Korea",
    "senegal":          "Senegal",
    "mexico":           "Mexico",
    "canada":           "Canada",
    "australia":        "Australia",
    "socceroos":        "Australia",
    "nigeria":          "Nigeria",
    "super eagles":     "Nigeria",
    "ivory coast":      "Ivory Coast",
    "côte d'ivoire":    "Ivory Coast",
    "bosnia":           "Bosnia-Herzegovina",
    "czech republic":   "Czechia",
    "curacao":          "Curaçao",
    "turkiye":          "Türkiye",
    "turkey":           "Türkiye",
    "congo":            "DR Congo",
    "cape verde":       "Cape Verde",
}

# ── DB helper ────────────────────────────────────────────────────────
_connection_pool = None

def get_db_pool():
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.SimpleConnectionPool(
            minconn=2,
            maxconn=20,
            dsn=os.getenv("DATABASE_URL")
        )
    return _connection_pool

def get_db():
    return get_db_pool().getconn()

def get_db_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def release_db(conn):
     if conn is not None:
        try:
            get_db_pool().putconn(conn)
        except Exception as e:
            print(f"[api] Error releasing connection: {e}")

# ── App ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(redis_subscribe())
    print("[api] WebSocket Redis server starting up")
    yield
    task.cancel()
    print("[api] WebSocket Redis server shutting down")

app = FastAPI(
    title="ScoreStream API",
    description="Real-time European football stats powered by Kafka + PySpark + PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def limit_size(request: Request, call_next):
    if request.headers.get('content-length'):
        if int(request.headers['content-length']) > 1_000_000:  # 1 MB limit
            return JSONResponse(status_code=413, content={"detail": "Request body too large"})
    return await call_next(request)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

async def redis_subscribe():
    redis = aioredis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

    pubsub = redis.pubsub()
    await pubsub.subscribe("scorestream.updates")
    print("[ws] Redis Subscriber started, listening for updates...")

    async for message in pubsub.listen():
        if message["type"] != "message":
            continue

        await manager.broadcast(message["data"])

def get_ttl(has_live: bool):
    return 10 if has_live else 30

# ── Routes ───────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "ScoreStream API",
        "version": "1.0.0",
        "endpoints": ["/games", "/games/{game_id}/stats", "/standings", "/standings/{top_n}", "/health", "/health/pipeline"],
    }

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()  # Keep connection open
    except WebSocketDisconnect:
        manager.disconnect(websocket)

## ── Health Checks ───────────────────────────────────────────────────

@app.get("/health")
def health():
    """Check that DB and cache are reachable."""
    status = {"api": "ok", "db": "unknown", "cache": "unknown"}
    conn = None
    
    try:
        conn = get_db()
        release_db(conn)
        status["db"] = "ok"
    except Exception as e:
        status["db"] = str(e)
    try:
        cache.ping()
        status["cache"] = "ok"
    except Exception as e:
        status["cache"] = str(e)
    return status

@app.get("/health/pipeline")
@limiter.limit("10/minute")
def health_pipeline(request: Request):
    """Check that the data pipeline is functioning correctly."""
    cached = cache.get("pipeline_health")
    if cached:
        return json.loads(cached)

    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)

        status = {"airflow": {}, "kafka": {}, "postgres": {}, "producer": {}}

        admin = KafkaAdminClient(bootstrap_servers="kafka:29092")
        consumer = KafkaConsumer(bootstrap_servers="kafka:29092")
        topics = ["sports.live.scores", "sports.standings"]

        # Check Kafka topic health by getting message counts for each topic
        for topic in topics:
            try:
                partitions = consumer.partitions_for_topic(topic)
                if not partitions:
                    status["kafka"][topic] = {"message_count": 0, "status": "unknown"}
                    continue
                
                tps = [TopicPartition(topic, p) for p in partitions]
                end_offsets = consumer.end_offsets(tps)
                total_messages = sum(end_offsets.values())
                status["kafka"][topic] = {"message_count": total_messages, "status": "healthy"}
            except Exception as e:
                status["kafka"][topic] = {"message_count": 0, "status": str(e)}

        consumer.close()
        admin.close()

        # Check PostgreSQL by running a simple query for each table
        try:
            cursor.execute("""
                SELECT
                    (SELECT COUNT(*) FROM games) AS games_count,
                    (SELECT MAX(last_updated) FROM games) AS last_game_update,
                    (SELECT COUNT(*) FROM goals) AS goals_count,
                    (SELECT MAX(created_at) FROM goals) AS last_goal_update,
                    (SELECT COUNT(*) FROM standings) AS standings_count,
                    (SELECT MAX(last_updated) FROM standings) AS last_standings_update
            """)
            
            stats = cursor.fetchone()

            status["postgres"]["games"] = {"count": stats["games_count"], "last_updated": stats["last_game_update"].isoformat() if stats["last_game_update"] else None, "status": get_status(stats["last_game_update"], 2)}
            status["postgres"]["goals"] = {"count": stats["goals_count"], "last_updated": stats["last_goal_update"].isoformat() if stats["last_goal_update"] else None, "status": get_status(stats["last_goal_update"], 5)}
            status["postgres"]["standings"] = {"count": stats["standings_count"], "last_updated": stats["last_standings_update"].isoformat() if stats["last_standings_update"] else None, "status": get_status(stats["last_standings_update"], 35)}
        except Exception as e:
            status["postgres"] = {"error": str(e)}

        # Check Airflow DAGs
        try:
            cursor.execute("""
                SELECT dag_id, state, execution_date, end_date
                FROM dag_run
                WHERE dag_id IN ('standings_refresh', 'daily_archive')
                ORDER BY execution_date DESC
            """)

            dag_runs = cursor.fetchall()

            for dag_run in dag_runs:
                if dag_run["dag_id"] not in status["airflow"]:
                    status["airflow"][dag_run["dag_id"]] = {
                        "last_run": dag_run["end_date"].isoformat() if dag_run["end_date"] else None,
                        "state": dag_run["state"],
                        "status": "healthy" if dag_run["state"] == "success" else "error" if dag_run["state"] == "failed" else "running"
                    }
        except Exception as e:
            status["airflow"] = {"error": str(e)}

        # Check producer health by querying metadata table
        try:
            cursor.execute("SELECT value, last_updated FROM pipeline_metadata WHERE key = 'last_poll'")
            result = cursor.fetchone()

            status["producer"]["last_poll"] = result["last_updated"].isoformat() if result else None
            status["producer"]["status"] = get_status(result["last_updated"], 2) if result else "unknown"
        except Exception as e:
            status["producer"] = {"status": str(e)}
        
        cache.setex("pipeline_health", 30, json.dumps(status, default=str))  # cache for 30s
        return status
    finally:
        release_db(conn)

def get_status(last_updated, threshold_minutes):
    if not last_updated:
        return "unknown"
    
    if last_updated.tzinfo is None:
        last_updated = last_updated.replace(tzinfo=timezone.utc)

    age = datetime.now(timezone.utc) - last_updated

    if age > timedelta(minutes=threshold_minutes):
        return "stale"
    
    return "healthy"

## ── Games ───────────────────────────────────────────────────────────

@app.get("/games")
@limiter.limit("60/minute")
def get_games(request: Request, status: Optional[str] = Query(None, regex="^(STATUS_IN_PROGRESS|STATUS_FINAL|STATUS_FULL_TIME|STATUS_SCHEDULED)$"), league: Optional[str] = Query(None, regex="^(bundesliga|ligue1|epl|laliga|seriea|worldcup)$")):
    """
    Return all games, optionally filtered by status and league.
    """
    cache_key = f"games:{status or 'all'}:{league or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)

        conditions = []
        params = []

        if status:
            conditions.append("status = %s")
            params.append(status)

        if league:
            conditions.append("league = %s")
            params.append(league)     

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        cursor.execute(f"""
            SELECT *
            FROM games
            {where}
            ORDER BY last_updated DESC, start_time ASC
        """, params)

        rows = [dict(r) for r in cursor.fetchall()]

        has_live = any(r["status"] in ("STATUS_IN_PROGRESS", "STATUS_FIRST_HALF", "STATUS_SECOND_HALF") for r in rows)
        ttl = get_ttl(has_live)

        # Serialize datetime objects
        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        cache.setex(cache_key, ttl, json.dumps(rows))  # cache 15s
        return rows
    finally:
        release_db(conn)

@app.get("/games/{game_id}")
def get_game(game_id: str = Path(..., min_length=1, max_length=50, regex="^[0-9]+$")):
    """Return a single game by ID."""
    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)

        cursor.execute("SELECT * FROM games WHERE game_id = %s", (game_id,))
        row = cursor.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        result = dict(row)
        for k, v in result.items():
            if hasattr(v, "isoformat"):
                result[k] = v.isoformat()
        return result
    finally:
        release_db(conn)

@app.get("/games/{game_id}/stats")
def get_game_stats(game_id: str):
    """Return stats for a specific game, ordered by time."""
    cache_key = f"stats:{game_id}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)
        cursor.execute("""
            SELECT *
            FROM goals
            WHERE game_id = %s
            ORDER BY seconds ASC
        """, (game_id,))
        rows = [dict(r) for r in cursor.fetchall()]

        if not rows:
            return []


        for row in rows:
            for k, v in row.items():
                if hasattr(v, 'isoformat'):
                    row[k] = v.isoformat()

        cache.setex(cache_key, 15, json.dumps(rows))
        return rows
    finally:
        release_db(conn)

## ── Standings ───────────────────────────────────────────────────────

@app.get("/standings")
def get_standings(league: str = 'epl'):
    """
    Return standings.
    """
    cache_key = f"standings:{league}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)

        if league == 'worldcup':
            cursor.execute("""
                SELECT *
                FROM standings
                WHERE league = %s
                ORDER BY group_name ASC, rank ASC
            """, (league, ))
        else:
            cursor.execute("""
                SELECT *
                FROM standings
                WHERE league = %s
                ORDER BY rank ASC
            """, (league, ))

        rows = [dict(r) for r in cursor.fetchall()]

        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        cache.setex(cache_key, 60, json.dumps(rows))  # cache 60s
        return rows
    finally:
        release_db(conn)

@app.get("/leagues")
def get_leagues():
    conn = None

    try:
        conn = get_db()
        cursor = get_db_cursor(conn)
        cursor.execute("SELECT DISTINCT league FROM games ORDER BY league ASC")
        leagues = [r["league"] for r in cursor.fetchall()]
        return leagues
    finally:        
        release_db(conn)

## ── Natural Language Q&A ───────────────────────────────────────────

CHART_SYSYTEM_PROMPT = """You are a data visualization expert for a football data pipeline application called ScoreStream.
Given a natural language question and SQL query results, and decide if it is better answered with a chart.

Return a JSON object with EXACTLY these field names — no variations:
{
    "should_chart": true or false,
    "chart_type": "bar" | "line" | "pie" | null,
    "title": "Chart title" | null,
    "x_key": "field name for x axis" | null,
    "y_key": "field name for y axis" | null,
    "data": [ array of objects ] | null,
    "color": "#hexcolor" | null
}

CRITICAL: Use exactly "x_key" and "y_key" — never "x_axis", "y_axis", "xKey", "yKey" or any other variation.

Rules:
- Use bar charts for comparisons (top scorers, standings, team comparisons)
- Use line charts for trends over time, especially when asked about form (form over last N games, goals per gameweek)
- Use pie charts for distributions (goals by league, win/draw/loss ratio, goal types breakdown)
- Never use timestamp or datetime fields (start_time, last_updated, created_at) as x_key
- For time-based charts use a formatted date string column like match_date or formatted_date
- For form charts x_key should be 'opponent', y_key should be 'points'
- should_chart = false for single-value results, scorer lists, or game recaps
- data must be a simplified array — only include the fields needed for the chart
- x_key and y_key must exactly match field names in the data array
- y_key must exactly match the field name being visualized in the question
- If the question asks about goal difference, y_key must be 'goal_diff' not 'points'
- If the questions asks about form, y_key must be 'points' not 'goal_diff'
- If the question asks about points, y_key must be 'points' not 'goal_diff'
- Never substitute one metric for another — use exactly what the user asked for
- Check the data fields carefully before setting x_key and y_key
- Return ONLY valid JSON, no explanation, no markdown, no backticks
"""

WORLD_CUP_CONTEXT = """
World Cup specific rules:

Data available:
- Games: all World Cup matches stored with league = 'worldcup'
- Goals: individual goal events for World Cup matches
- Standings: group stage standings with group_name field (e.g. 'Group A')
- Teams are national teams — home_team_name and away_team_name are country names

Stages:
- Group stage: teams play 3 games each, top 2 per group advance
- Round of 32: first knockout round (48 teams → 24)
- Round of 16: second knockout round  
- Quarter-finals: 8 teams
- Semi-finals: 4 teams
- Third place playoff: losers of semi-finals
- Final: 2 teams

Status values for knockout rounds:
- STATUS_FULL_TIME — game ended in 90 minutes
- STATUS_EXTRA_TIME — game went to extra time
- STATUS_PENALTIES — game decided on penalties

Example queries:

-- Which teams have qualified from their group?
SELECT team_name, group_name, points, wins, draws, losses, goals_for, goals_against, goal_diff, rank, note
FROM standings
WHERE league = 'worldcup'
AND note ILIKE '%advance%'
ORDER BY group_name ASC, rank ASC;

-- Show me Group A standings
SELECT team_name, matches_played, wins, draws, losses, goals_for, goals_against, goal_diff, points, rank
FROM standings
WHERE league = 'worldcup'
AND group_name = 'Group A'
ORDER BY rank ASC;

-- Who has scored the most goals at the World Cup?
SELECT 
    gl.player_name,
    COUNT(*) as goals,
    MAX(CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END) as country
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'worldcup'
AND gl.own_goal = false
GROUP BY gl.player_name
ORDER BY goals DESC
LIMIT 10;

-- Which countries have scored the most goals?
SELECT 
    CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END AS country,
    COUNT(*) as goals
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'worldcup'
AND gl.own_goal = false
GROUP BY country
ORDER BY goals DESC;

-- What were the results in the group stage?
SELECT home_team_name, away_team_name, home_score, away_score, start_time, status_detail
FROM games
WHERE league = 'worldcup'
AND status IN ('STATUS_FULL_TIME', 'STATUS_FINAL', 'STATUS_EXTRA_TIME', 'STATUS_PENALTIES')
ORDER BY start_time ASC;

-- Which games went to penalties?
SELECT home_team_name, away_team_name, home_score, away_score, start_time, status_detail
FROM games
WHERE league = 'worldcup'
AND status = 'STATUS_PENALTIES'
ORDER BY start_time ASC;

-- Show me all World Cup games for a specific country
SELECT home_team_name, away_team_name, home_score, away_score, start_time, status_detail
FROM games
WHERE league = 'worldcup'
AND (home_team_name ILIKE '%England%' OR away_team_name ILIKE '%England%')
ORDER BY start_time ASC;

-- Who scored in a specific World Cup match?
SELECT 
    gl.player_name,
    gl.minute,
    gl.goal_type,
    gl.own_goal,
    gl.penalty_goal,
    CASE 
        WHEN gl.team_id = gm.home_id THEN gm.home_team_name
        WHEN gl.team_id = gm.away_id THEN gm.away_team_name
    END AS scored_for,
    gm.home_team_name,
    gm.away_team_name,
    gm.home_score,
    gm.away_score
FROM goals gl
JOIN games gm ON gl.game_id = gm.game_id
WHERE gm.league = 'worldcup'
AND (gm.home_team_name ILIKE '%Brazil%' OR gm.away_team_name ILIKE '%Brazil%')
AND gm.game_id = (
    SELECT game_id FROM games
    WHERE league = 'worldcup'
    AND (home_team_name ILIKE '%Brazil%' OR away_team_name ILIKE '%Brazil%')
    AND status NOT IN ('STATUS_SCHEDULED', 'STATUS_IN_PROGRESS', 'STATUS_HALFTIME')
    ORDER BY start_time DESC
    LIMIT 1
)
ORDER BY gl.seconds ASC;
"""

def expand_aliases(question: str) -> str:
    q = question.lower()
    for alias, full in ALIAS_MAP.items():
        if alias in q:
            question = question.replace(alias, full)
            question = question.replace(alias.title(), full)  # also replace title case
            question = question.replace(alias.upper(), full)  # also replace upper case
    return question

@app.post("/chat")
def chat(request: Request, body: dict):
    question = body.get("question", "").strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question is required")

    conversation = body.get("conversation", [])

    expanded_question = expand_aliases(question)
    print(f"[chat] Received question: {question} → Expanded: {expanded_question}")
    
    conn = None
    try:
        messages = conversation + [{"role": "user", "content": expanded_question}]

        sql_response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=f"""You are a SQL expert for a football data pipeline application called ScoreStream. 
            Given a natural language question, write a PostgreSQL query to answer it based on the following database schema:\n
            {DB_SCHEMA}

            {TEAM_ALIASES}

            {WORLD_CUP_CONTEXT}

            {WORLD_CUP_ALIASES}

            Rules:
            - For completed or finished games use: 
            status IN ('STATUS_FULL_TIME', 'STATUS_FINAL', 'STATUS_ABANDONED')
            - When finding a team's last game use:
            status NOT IN ('STATUS_SCHEDULED', 'STATUS_IN_PROGRESS', 'STATUS_HALFTIME', 'STATUS_FIRST_HALF', 'STATUS_SECOND_HALF')
            This catches any completed status including abandoned games
            - For questions like 'what happened', 'tell me about', 'how did it go', 'recap' — 
            always JOIN goals and include scorer information, not just the final score
            - When asked about "top goal scorers" or "who scored the most goals", use the season_stats table, not the goals table, since the goals table only contains recent events and may not have complete season data, same goes for questions about assists and penalties
            - When asked about the current season's stats for a player, use the season_stats table, not the goals table
            - When asked about a team's form over a period of time, use points as the metric, not goals scored
            - ONLY use these tables: games, goals, standings — never reference any other table
            - Never use tables like season_stats, player_stats, match_stats or any table not in the schema above
            - Never filter by season year — the database contains whatever data has been ingested, no season column exists
            - For top scorer queries always COUNT(*) from the goals table joined with games
            - Never use season = 2024 when checking season stats, use season = 2025 for the 2025/26 season since season is defined as the start year in the schema
            - Always filter out own goals with AND gl.own_goal = false when counting goals for a player
            - Any question about open play goals, they refer to any goal in the goals table where penalty_goal = false and the goal_type does not contain 'Penalty' or 'Free-kick' — do not assume that goal_type will always include the word 'Goal' for open play goals, as there are many variations in the data
            - When searching for FC Barcelona specifically, always use:
            (home_team_name ILIKE '%Barcelona%' AND home_team_name NOT ILIKE '%Espanyol%')
            Never use ILIKE '%Barcelona%' alone as it matches Espanyol de Barcelona
            - Similarly for other teams whose names appear inside other team names:
            AC Milan: use ILIKE '%Milan%' AND NOT ILIKE '%Inter%'
            Real Madrid: use ILIKE '%Real Madrid%' (specific enough already)
            Real Betis: use ILIKE '%Betis%' not ILIKE '%Real%'
            Real Sociedad: use ILIKE '%Sociedad%' not ILIKE '%Real%'
            - When the question mentions 'FC Barcelona', always exclude Espanyol:
            home_team_name ILIKE '%Barcelona%' AND home_team_name NOT ILIKE '%Espanyol%'
            - When the question mentions 'RCD Espanyol' or 'Espanyol', use ILIKE '%Espanyol%' alone
            - Any question about a specific game should always include goal scorer data via LEFT JOIN
            - Return ONLY the SQL query, no explanation, no markdown, no backticks
            - When asked to give information about data over the course of a period of time, if the data doesn't go that far back, use data from the database that goes as far back as possible instead of just saying there's not enough data
            - Use ILIKE for team name searches — always search both home_team_name and away_team_name
            - When a user mentions a team by nickname or acronym, expand it to the full ESPN name using the aliases above
            - For partial name matches use ILIKE '%partial%' — e.g. 'Paris Saint-Germain' → ILIKE '%Paris Saint-Germain%'
            - For 'last game' use ORDER BY start_time DESC LIMIT 1 on completed games
            - For 'today' use CURRENT_DATE
            - For 'this week' use start_time >= CURRENT_DATE - INTERVAL '7 days'
            - For form queries always include an 'opponent' column as the x-axis label
            - For form queries use 'points' as the y-axis (3=Win, 1=Draw, 0=Loss)
            - Format dates using TO_CHAR(start_time, 'Mon DD') for readable labels
            - Never use raw timestamp fields as x-axis labels for charts
            - When asked questions like for any upcoming games soon, look for games with the status='STATUS_SCHEDULED' and start_time in the future, ordered by start_time ASC
            - When asked about games that are or were live today, or live right now, look for games with start_time = CURRENT_DATE
            - Limit results to 20 rows maximum
            - For league names use: epl, laliga, bundesliga, seriea, ligue1, worldcup
            - For World Cup questions always filter with league = 'worldcup'
            - National teams use country names — search with ILIKE '%England%' not '%ENG%'
            - World Cup standings have a group_name field — always include it when querying standings
            - For knockout round results check status IN ('STATUS_FULL_TIME', 'STATUS_FINAL', 'STATUS_EXTRA_TIME', 'STATUS_PENALTIES')
            - Penalty shootout scores are NOT stored — only the score after extra time is recorded
            - For 'who qualified' questions use the note field in standings — filter WHERE note ILIKE '%advance%'
            - For group standings always ORDER BY rank ASC within each group_name
            - The 2026 World Cup has 48 teams split into 12 groups (A through L)
            - Top 2 from each group advance plus 8 best third-place teams advance to Round of 32
            - Never confuse club team names with national team names
            - Never use DROP, DELETE, UPDATE, INSERT or any write operations
            - When asking about a team's scorers always JOIN goals with games on game_id
            - Every query involving goals MUST include a 'scored_for' column computed as:
                CASE WHEN g.team_id = gm.home_id THEN gm.home_team_name
                    WHEN g.team_id = gm.away_id THEN gm.away_team_name
                    ELSE 'Unknown Team' END AS scored_for
            - If the question cannot be answered return: SELECT 'I cannot answer that with the available data' AS message
            """,
            messages=messages
        )

        sql = sql_response.content[0].text.strip()
        print(f"[chat] Generated SQL: {sql}")

        forbidden = ["DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE"]
        if any(word in sql.upper() for word in forbidden):
            return {"answer": "I can only answer read-only questions about match data. Please rephrase your question.", "chart": None}
        
        conn = get_db()
        cursor = get_db_cursor(conn)
        cursor.execute(sql)
        rows = [dict(r) for r in cursor.fetchall()]

        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        if not rows:
            # Detect what kind of question it was and return appropriate message
            q_lower = expanded_question.lower()
            
            if any(word in q_lower for word in ['live', 'in progress', 'playing now', 'currently playing']):
                empty_message = "There are no live games right now. Check back during a matchday."
            elif any(word in q_lower for word in ['upcoming', 'next', 'tomorrow', 'today', 'schedule', 'fixture']):
                empty_message = "There are no upcoming games in the database at the moment. The producer polls ESPN every 30 seconds so fixtures should appear shortly before matchday."
            elif any(word in q_lower for word in ['standing', 'table', 'rank', 'position']):
                empty_message = "No standings data found for that league. Try triggering the standings DAG or wait for the next scheduled refresh."
            else:
                empty_message = "I couldn't find any data matching that query. Try rephrasing or asking about a different league or time period."

            return {
                "answer": empty_message,
                "chart":  None,
                "sql":    sql,
            }
        
        chart_response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=CHART_SYSYTEM_PROMPT,
            messages=[
                {"role": "user", "content": f"Question: {expanded_question}\n\nData: {json.dumps(rows, default=str)}"}
            ]
        )

        answer_response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=500,
            system=f"""You are a helpful assistant for a football data pipeline application called ScoreStream. 
            Given a natural language question and the SQL query results, provide a clear and concise, natural language answer to the user.

            Rules:
            - If status is 'STATUS_ABANDONED', note that the game was abandoned and goals shown are from before the abandonment
            - Always use the 'scored_for' field to say which team a player scored for — never guess from the player name
            - Format the final score on its own line as: Home Team 2 - 1 Away Team
            - List each goal scorer on its own line in this format:
            ⚽ Player Name (Team Name) 23' — Goal Type
            🎯 Player Name (Team Name) 45' — Penalty
            🔴 Player Name (Team Name) 67' — Own Goal
            - Put a blank line between the score and the scorer list
            - If own_goal is true use 🔴 and note it as an own goal
            - If penalty_goal is true use 🎯
            - Otherwise use ⚽
            - Keep any summary sentence brief — one line at most
            - If player_name is null for all rows, the game was a 0-0 draw — say so clearly
            - When asked about upcoming games or games right now, if the data shows no games, say something like 'There are no scheduled games for that period.' or 'There are no scheduled games today.', rather than "No data found."
            - When asked about goal difference always SELECT goal_diff not points
            - When asked about open play goals, that includes any goal where penalty_goal = false and goal_type does not contain 'Penalty' or 'Free-kick', there's no other type of goal in the data, so if the question is about open play goals SELECT all goals that are not penalties or free-kicks, or from other set pieces
            - When asked about form, points, or standings SELECT points
            - Never substitute goal_diff with points or vice versa
            - Always SELECT only the columns relevant to the question — 
            if asking about goal difference, include goal_diff and team_name, not points
            - For 'what happened' questions give a full match summary:
            first the score, then list each scorer, then a brief one-line summary
            - For World Cup results format as: Country A 2 - 1 Country B (AET) for extra time
            - For penalty shootouts note: 'decided on penalties' since penalty scores aren't stored
            - For group standings show the group name as a header
            - For qualification questions list which teams advanced and from which group
            - Use country names not abbreviations in responses
            - Never mention SQL or databases
            - If data is empty say so clearly
            """,
            messages=[
                {"role": "user", "content": f"Question: {expanded_question}\n\nData: {json.dumps(rows, default=str)}"}
            ]
        )

        chart = None
        try:
            chart_text = chart_response.content[0].text.strip()

            if not chart_text:
                print("[chat] Empty chart response — skipping chart")
            else :
                # Strip markdown code fences with regex — handles ```json, ```, and newlines
                clean = re.sub(r'^```(?:json)?\s*', '', chart_text.strip())
                clean = re.sub(r'\s*```$', '', clean)
                clean = clean.strip()

                chart_data = json.loads(clean)

                # Normalize x/y key variations
                chart_data['x_key'] = (
                    chart_data.get('x_key') or chart_data.get('x_axis') or
                    chart_data.get('xKey') or chart_data.get('x')
                )
                chart_data['y_key'] = (
                    chart_data.get('y_key') or chart_data.get('y_axis') or
                    chart_data.get('yKey') or chart_data.get('y')
                )

                if chart_data.get('should_chart'):
                    if chart_data.get('data') and chart_data.get('x_key') and chart_data.get('y_key'):
                        first_row = chart_data['data'][0] if chart_data['data'] else {}
                        if chart_data['y_key'] not in first_row:
                            numeric_keys = [k for k, v in first_row.items() if isinstance(v, (int, float))]
                            if numeric_keys:
                                chart_data['y_key'] = numeric_keys[0]
                        chart = chart_data

        except json.JSONDecodeError as e:
            print(f"[chat] JSON decode error: {e}")
            print(f"[chat] Clean text was: {clean[:200] if 'clean' in locals() else 'not reached'}")
        except Exception as e:
            print(f"[chat] Chart error: {e}")

        return {"answer": answer_response.content[0].text.strip(), "sql": sql, "chart": chart}
    
    except Exception as e:
        print(f"[chat] Error: {e}")
        return {"answer": "Sorry, I couldn't process your question. Try rephrasing it or ask something else about football matches."}
    finally:
        release_db(conn)