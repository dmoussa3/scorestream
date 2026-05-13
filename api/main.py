"""
ScoreStream — FastAPI serving layer
Serves live scores, player stats, and standings from PostgreSQL with Redis caching.
"""

import json
import os
from contextlib import asynccontextmanager

import psycopg2
import psycopg2.extras
import redis

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from kafka import KafkaAdminClient, KafkaConsumer
from kafka.structs import TopicPartition

from datetime import datetime, timedelta, timezone

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

# ── DB helper ────────────────────────────────────────────────────────
def get_db():
    return psycopg2.connect(**DB_CONFIG, cursor_factory=psycopg2.extras.RealDictCursor)

# ── App ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[api] ScoreStream API starting up")
    yield
    print("[api] ScoreStream API shutting down")

app = FastAPI(
    title="ScoreStream API",
    description="Real-time EPL stats powered by Kafka + PySpark + PostgreSQL",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Routes ───────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {
        "service": "ScoreStream API",
        "version": "1.0.0",
        "endpoints": ["/games", "/games/{game_id}/stats", "/standings", "/standings/{top_n}", "/health", "/health/pipeline"],
    }

## ── Health Checks ───────────────────────────────────────────────────

@app.get("/health")
def health():
    """Check that DB and cache are reachable."""
    status = {"api": "ok", "db": "unknown", "cache": "unknown"}
    try:
        conn = get_db()
        conn.close()
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
def health_pipeline():
    """Check that the data pipeline is functioning correctly."""
    cached = cache.get("pipeline_health")
    if cached:
        return json.loads(cached)

    conn = get_db()
    cursor = conn.cursor()

    status = {"airflow": {}, "kafka": {}, "postgres": {}, "producer": {}}

    admin = KafkaAdminClient(bootstrap_servers="kafka:29092")
    consumer = KafkaConsumer(bootstrap_servers="kafka:29092")
    topics = ["epl.live.scores", "epl.standings"]

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
            WHERE dag_id IN ('epl_standings_refresh', 'epl_daily_archive')
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
    
    conn.close()
    cache.setex("pipeline_health", 30, json.dumps(status, default=str))  # cache for 30s
    return status

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
def get_games(status: str | None = None):
    """
    Return all games, optionally filtered by status.
    ?status=STATUS_IN_PROGRESS  — live games only
    ?status=STATUS_FINAL        — completed games
    """
    cache_key = f"games:{status or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = get_db()
    cursor = conn.cursor()

    if status:
        cursor.execute("""
            SELECT game_id, home_team, away_team, home_id, away_id, home_score, away_score,
                   status, period, clock, start_time, last_updated
            FROM games
            WHERE status = %s
            ORDER BY last_updated DESC
        """, (status,))
    else:
        cursor.execute("""
            SELECT game_id, home_team_name, home_id, home_team, away_team_name, away_id, away_team, home_score, away_score,
                   status, period, clock, start_time, last_updated
            FROM games
            ORDER BY last_updated DESC
        """)

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    # Serialize datetime objects
    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()

    cache.setex(cache_key, 15, json.dumps(rows))  # cache 15s
    return rows


@app.get("/games/{game_id}")
def get_game(game_id: str):
    """Return a single game by ID."""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM games WHERE game_id = %s", (game_id,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

    result = dict(row)
    for k, v in result.items():
        if hasattr(v, "isoformat"):
            result[k] = v.isoformat()
    return result


@app.get("/games/{game_id}/stats")
def get_game_stats(game_id: str):
    """Return stats for a specific game, ordered by time."""
    cache_key = f"stats:{game_id}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT player_name, team_id, minute, seconds, goal_type, own_goal, penalty_goal
        FROM goals
        WHERE game_id = %s
        ORDER BY seconds ASC
    """, (game_id,))
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    if not rows:
        return []

    cache.setex(cache_key, 15, json.dumps(rows))
    return rows

## ── Standings ───────────────────────────────────────────────────────

@app.get("/standings")
@app.get("/standings/{top_n:int}")
def get_standings(top_n: int | None = None):
    """
    Return standings.
    """
    cache_key = f"standings:{top_n or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = get_db()
    cursor = conn.cursor()

    if top_n is not None:
        cursor.execute("""
            SELECT *
            FROM standings
            ORDER BY rank ASC
            LIMIT %s
        """, (top_n,))
    else:
        cursor.execute("""
            SELECT *
            FROM standings
            ORDER BY rank ASC
        """)

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()

    for row in rows:
        for k, v in row.items():
            if hasattr(v, "isoformat"):
                row[k] = v.isoformat()

    cache.setex(cache_key, 60, json.dumps(rows))  # cache 60s
    return rows