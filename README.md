# ScoreStream

A real-time european football data pipeline built with Kafka, PySpark Structured Streaming, Apache Airflow, PostgreSQL, and FastAPI — containerized end-to-end with Docker Compose.

ScoreStream ingests live match data from **the 5 major European leagues** via the ESPN public API, streams events through Kafka, processes them with PySpark in real time, and serves the results via a REST API with Redis caching and WebSocket push. A parallel Airflow batch layer handles scheduled standings refreshes and daily Parquet archiving across all leagues.

---

## Supported Leagues

| League | ESPN Code | Teams |
|---|---|---|
| Premier League | eng.1 | 20 |
| La Liga | esp.1 | 20 |
| Bundesliga | ger.1 | 18 |
| Serie A | ita.1 | 20 |
| Ligue 1 | fra.1 | 18 |

Additional leagues can be added by appending to the `LEAGUES` dict in `espn_producer.py` — no other changes required.

---

## Architecture

```
ESPN Public API (polled every 30s — 5 leagues)
        │
        ▼
Python Producer
        │  publishes to Kafka topics
        ▼
┌─────────────────────────────────────┐
│  sports.live.scores                 │  game state + goal events (all leagues)
│  sports.standings                   │  full league table snapshots
└─────────────────────────────────────┘
        │
        ▼
PySpark Structured Streaming
  ├── process_games     →  games table       (upsert, every 10s)
  ├── process_goals     →  goals table       (deduplication via composite key)
  └── process_standings →  standings table   (upsert per league, every 30s)
        │
        ▼
PostgreSQL ←→ Redis (dynamic TTL)
        │          │
        │          └──▶ WebSocket push → React frontend
        ▼
FastAPI REST API + WebSocket

Airflow (parallel batch layer)
  ├── standings_refresh  →  runs every 30 min, all 5 leagues
  └── epl_daily_archive  →  runs at midnight, writes Parquet snapshots
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Ingestion | Python, ESPN Public API |
| Message broker | Apache Kafka 7.4 |
| Stream processing | PySpark 3.4 Structured Streaming |
| Orchestration | Apache Airflow 2.8 |
| Storage | PostgreSQL 15, Parquet |
| Caching | Redis 7 |
| API | FastAPI, Uvicorn |
| Infrastructure | Docker, Docker Compose |

---

## Services

| Service | Port | Description |
|---|---|---|
| FastAPI | 8000 | REST API serving live stats |
| Frontend | 3000 | React Dashboard UI |
| Airflow | 8081 | Pipeline orchestration UI |
| Kafka UI | 8090 | Topic and message inspection |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | API response cache |

---

## API Endpoints

```
GET /                           — Service info
GET /health                     — DB and cache connectivity check
GET /health/pipeline            — Full pipeline component status
GET /games                      — All games, filterable by ?status= and ?league=
GET /games/{game_id}            — Single game by ID
GET /games/{game_id}/stats      — Goal events for a specific game
GET /standings                  — League table, filterable by ?league=
GET /leagues                    — List of all leagues with data
WS  /ws                         — WebSocket for real-time push updates
```

---

## Dashboard

A React single-page application with four views and a league selector:

**League Selector** — Switch between Premier League, La Liga, Bundesliga, Serie A, and Ligue 1. Scores and standings update automatically when switching leagues.

**Live Scores** — Match cards showing live scores, status, team logos, and kickoff times. Updates in real time via WebSocket push — no polling. Click any card to view match details.

**League Table** — Full standings with position, points, goal difference, and zone indicators. Champions League positions marked in green, Europa League in purple, relegation in red.

**Match Detail** — Per-game view with score header, team logos, goal scorers, and a visual goal timeline. For live games the timeline acts as a progress bar with a real-time interpolated clock between API updates.

**Pipeline Health** — Internal dashboard showing status of every pipeline component — producer last poll, Kafka topic message counts, PostgreSQL row counts per table, and Airflow DAG last run status.

Open the dashboard at `http://localhost:3000` after starting the stack.

## Data Model

**games** — Live match state, upserted on every poll cycle. Tracks score, period, clock, and match status.

**goals** — Individual goal events extracted from the ESPN details array. Deduplicated using a composite unique constraint on `(game_id, player_id, minute)` to prevent duplicate inserts across repeated poll cycles.

**standings** — Full EPL table. Replaced atomically on each Airflow run and Spark batch using delete-then-insert within a single transaction.

**archive/games/YYYY-MM-DD.parquet** — Daily Parquet snapshots of the games table, written by the Airflow archive DAG.

---

## Setup

### Prerequisites

- Docker Desktop running

### Start the full stack

```bash
git clone https://github.com/dmoussa3/scorestream
cd scorestream
docker compose up --build
```

First run takes 3–5 minutes — Spark downloads its Kafka and PostgreSQL JARs via Maven on startup. Subsequent starts are fast since the Ivy cache is persisted via a Docker volume.

## Environment

This project uses hardcoded development credentials in `docker-compose.yml`. 
These are intentional for local development. Do not use these credentials 
in any production deployment.

Default credentials:
- PostgreSQL: `admin` / `password`
- Airflow UI: check logs on first startup for auto-generated password
- Kafka UI: no authentication required

### Verify everything is running

```bash
# Check all containers are healthy
docker compose ps

# Confirm data is flowing
curl http://localhost:8000/health
curl http://localhost:8000/games
curl http://localhost:8000/standings
```

# Open the dashboard
open http://localhost:3000
```

The dashboard connects to the API automatically. The Pipeline Health tab is the fastest way to verify all components are healthy after startup.

### Airflow UI

Open `http://localhost:8081`. Find the generated admin password:

```bash
docker compose logs airflow-webserver | grep -i "password"
```

Two DAGs will be present — toggle both on. Manually trigger `epl_daily_archive` to generate the first Parquet snapshot.

### Stop

```bash
docker compose down          # stop, keep data
docker compose down -v       # stop and wipe all data
```
---

## Engineering Challenges

Building this project involved working through several non-trivial distributed systems problems:

**Kafka topic timing** — Spark Structured Streaming fails with `UnknownTopicOrPartitionException` if topics don't exist when queries start. Solved by adding a `kafka-init` container that pre-creates topics and completes before Spark starts, using Docker Compose's `service_completed_successfully` condition.

**PySpark on Apple Silicon** — PySpark 3.4 requires Java 11 specifically. The default `openjdk-11-jdk` package is unavailable on ARM64 Debian Trixie. Solved by switching the base image to `eclipse-temurin:11-jdk-jammy`, which provides ARM64-compatible Java 11.

**JAR version conflicts** — Manually downloading `spark-sql-kafka` and `kafka-clients` separately caused `ClassNotFoundException` due to version mismatches between the connector and client. Solved by switching to `spark.jars.packages`, which lets Spark resolve all transitive dependencies from Maven with guaranteed version compatibility.

**Kafka offset drift** — After container restarts, Spark checkpoints retained stale offsets that no longer existed in Kafka due to retention expiry. This caused repeated `UnknownTopicOrPartitionException` on the standings stream. Solved by increasing Kafka log retention to 24 hours and adding `failOnDataLoss=false` to the stream config.

**Goals always null despite correct schema** — The `goals` field parsed as null in every batch despite the Kafka messages containing goal data. Root cause: `minute` was defined as `IntegerType` in the PySpark schema but the producer publishes it as a string (e.g. `"8'"`, `"90'+3'"`). When `from_json` encountered a type mismatch on any field in a nested struct, it nulled the entire array. Fixed by changing `minute` to `StringType`.

**Standings schema mismatch** — The producer publishes the full 20-team standings as a single Kafka message containing a JSON array. The initial PySpark schema defined standings as a single struct, causing `from_json` to return null for every message. Fixed by wrapping the schema in `ArrayType` and using `explode()` to flatten the array into individual rows before writing.

**Checkpoint filesystem deadlock** — On macOS, concurrent Spark stream startups occasionally cause `Resource deadlock avoided` errors when multiple queries try to write checkpoint temp files simultaneously. This is a macOS-specific filesystem locking behavior and self-recovers on retry. Mitigated by staggering stream startups with a small delay between each query.

**React polling and clock interpolation** — The match detail view polls the API every 15 seconds for live game data, but ESPN's public API only updates its clock roughly every 60 seconds. To make the progress bar and clock feel real-time, the frontend interpolates between server updates using a `setInterval` ticker that increments elapsed seconds every second, resetting to the true server value on each API response. Two separate state variables keep the display clock and bar position independent — the clock ticks smoothly while the bar only moves on confirmed server data.

**Goal timeline positioning** — Goals are positioned on the timeline using `clock.value` from the ESPN details array, which represents elapsed match time in seconds. This avoids parsing display strings like `"90'+3'"` and handles stoppage time naturally since the raw seconds value is monotonically increasing regardless of display format.

**Logo contrast on dark backgrounds** — ESPN team logos for light-colored clubs (Tottenham, etc.) are invisible on dark card backgrounds. Fixed by wrapping every logo in a white circular container so all logos have guaranteed contrast regardless of their color scheme.

**Multi-league pipeline scaling** — Extending from a single EPL feed to five concurrent leagues required generalizing every layer — the producer loops over a `LEAGUES` dict, Kafka topics were renamed from `epl.*` to `sports.*`, the database schema added a `league` column with a composite primary key on `(team_id, league)` for standings, and the API added `?league=` filter parameters throughout. The architecture required no structural changes — only parameterization.

**WebSocket real-time push** — Replaced frontend polling with a Redis pub/sub → WebSocket push architecture. Spark publishes a lightweight notification to Redis after each batch commit. FastAPI's async Redis subscriber receives the notification and broadcasts to all connected WebSocket clients via the `ConnectionManager`. The frontend triggers a targeted refetch on receiving the push rather than on a fixed interval, reducing API load during quiet periods while ensuring near-instant updates during live matches.

**datetime JSON serialization** — PostgreSQL returns Python `datetime` objects which are not JSON serializable by default. Added a serialization loop across all endpoints that converts any field with an `isoformat` method before caching or returning. The bug surfaced only for newly cached endpoints since existing cached responses returned the pre-serialized string values.

---

## Project Structure

```
scorestream/
├── docker-compose.yml
├── restart.sh                     # safe restart script — clears checkpoints
├── sql/
│   └── init.sql
├── producer/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── espn_producer.py           # ESPN API → Kafka (5 leagues)
├── spark/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── streaming_job.py           # PySpark Structured Streaming consumer
├── dags/
│   ├── standings_refresh.py       # Airflow DAG — 30 min standings refresh (all leagues)
│   └── epl_daily_archive.py       # Airflow DAG — nightly Parquet archive
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                    # FastAPI + WebSocket endpoints
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── public/
│   │   └── index.html
│   └── src/
│       ├── App.jsx                # League selector, WebSocket indicator
│       ├── index.js
│       ├── hooks/
│       │   ├── usePoll.js         # Polling hook (MatchesTab, PipelineTab)
│       │   ├── useWebSocket.js    # WebSocket connection with auto-reconnect
│       │   ├── useNotifications.js
│       │   ├── useSubscriptions.js
│       │   └── useGameWatcher.js
│       └── components/
│           ├── ScoresTab.jsx      # WebSocket-triggered refetch + league filter
│           ├── StandingsTab.jsx   # WebSocket-triggered refetch + league filter
│           ├── MatchesTab.jsx     # usePoll at 15s
│           └── PipelineTab.jsx    # usePoll at 60s
├── checkpoints/
├── archive/
└── README.md
```

---

## What's Next (Phase 5)

- Replace local Kafka with AWS MSK or Kinesis Data Streams
- Replace local Parquet storage with S3
- Replace local Spark with AWS Glue managed jobs
- Deploy FastAPI on EC2 behind an Application Load Balancer
- Deploy frontend on S3 + CloudFront for global CDN delivery
- Add CloudWatch monitoring and alerting
- Add Champions League and Europa League support
- Add historical analytics tab using archived Parquet data

---

## Author

Daniel Moussa — [dmoussa3.github.io](https://dmoussa3.github.io) — [LinkedIn](https://linkedin.com/in/daniel-moussa3) — [GitHub](https://github.com/dmoussa3)