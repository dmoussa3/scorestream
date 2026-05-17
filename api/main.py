"""
ScoreStream — FastAPI serving layer
Serves live scores, player stats, and standings from PostgreSQL with Redis caching.
"""

import json
import os
from contextlib import asynccontextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
import psycopg2.extras
import redis

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
    conn = get_db_pool().getconn()
    return conn

def get_db_cursor(conn):
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

def release_db(conn):
    get_db_pool().putconn(conn)

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
    allow_methods=["GET"],
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

    conn = get_db()

    try:
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
def get_games(request: Request, status: Optional[str] = Query(None, regex="^(STATUS_IN_PROGRESS|STATUS_FINAL|STATUS_FULL_TIME|STATUS_SCHEDULED)$"), league: Optional[str] = Query(None, regex="^(bundesliga|ligue1|epl|laliga|seriea)$")):
    """
    Return all games, optionally filtered by status and league.
    """
    cache_key = f"games:{status or 'all'}:{league or 'all'}"
    cached = cache.get(cache_key)
    if cached:
        return json.loads(cached)

    conn = get_db()

    try:
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
    conn = get_db()

    try:
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

    conn = get_db()

    try:
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

    conn = get_db()

    try:
        cursor = get_db_cursor(conn)

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
    conn = get_db()

    try:
        cursor = get_db_cursor(conn)
        cursor.execute("SELECT DISTINCT league FROM games ORDER BY league ASC")
        leagues = [r["league"] for r in cursor.fetchall()]
        return leagues
    finally:        
        release_db(conn)