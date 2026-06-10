# ScoreStream

A real-time football data pipeline built with Kafka, PySpark Structured Streaming, Apache Airflow, PostgreSQL, and FastAPI — containerized end-to-end with Docker Compose.

ScoreStream ingests live match data from **5 major European leagues and the FIFA World Cup** via the ESPN public API, streams events through Kafka, processes them with PySpark in real time, and serves the results via a REST API with Redis caching and WebSocket push. A parallel Airflow batch layer handles scheduled standings refreshes, season stats aggregation, and daily Parquet archiving. A natural language chat interface powered by Claude allows users to query live pipeline data in plain English.

---

## Architecture

```
ESPN Public API (polled every 15s — 6 competitions)
        │
        ▼
Python Producer
        │  publishes to Kafka topics
        ▼
┌─────────────────────────────────────┐
│  sports.live.scores (3 partitions)  │  game state + goal events
│  sports.standings   (1 partition)   │  full league/group table snapshots
└─────────────────────────────────────┘
        │
        ▼
PySpark Structured Streaming
  ├── process_games     →  games table       (upsert, every 5s)
  └── process_goals     →  goals table       (dedup via unique constraint)
        │
        ▼
PostgreSQL ←→ Redis (dynamic TTL)
        │          │
        │          └──▶ Redis pub/sub → WebSocket push → React frontend
        ▼
FastAPI REST API + WebSocket (/ws)

Airflow (parallel batch layer)
  ├── standings_refresh    →  every 30 min, all 6 competitions
  ├── season_stats_refresh →  every 15 min, aggregates goals into season_stats
  └── epl_daily_archive    →  nightly Parquet snapshots to ./archive/

Claude AI Chat (/chat)
  ├── SQL generation       →  natural language → PostgreSQL query
  ├── Query execution      →  safe read-only execution
  ├── Chart detection      →  decides bar/line/pie or text response
  └── Answer formatting    →  raw rows → natural language + optional chart
```

---

## Supported Competitions

| Competition | ESPN Code | Teams | Type |
|---|---|---|---|
| Premier League | eng.1 | 20 | Club |
| La Liga | esp.1 | 20 | Club |
| Bundesliga | ger.1 | 18 | Club |
| Serie A | ita.1 | 20 | Club |
| Ligue 1 | fra.1 | 20 | Club |
| FIFA World Cup | fifa.world | 48 | National |

Additional competitions can be added by appending to the `LEAGUES` dict in `espn_producer.py`.

---

## Services

| Service | Port | Description |
|---|---|---|
| FastAPI | 8000 | REST API + WebSocket + AI chat endpoint |
| Frontend | 3000 | React dashboard UI |
| Airflow | 8081 | Pipeline orchestration UI |
| Kafka UI | 8090 | Topic and message inspection |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | API response cache + pub/sub broker |

---

## Database Schema

**games** — live and historical match data
```
game_id, league, home_team, away_team, home_team_name, away_team_name,
home_id, away_id, home_logo, away_logo, home_score, away_score,
status, status_detail, period, clock, start_time, last_updated
```

**goals** — individual goal events
```
id, game_id, league, player_id, player_name, team_id,
minute, seconds, goal_type, own_goal, penalty_goal, created_at
UNIQUE (game_id, player_id, seconds)
```

**standings** — league and group tables
```
team_id, league, team_name, group_name, wins, draws, losses,
points, goals_for, goals_against, goal_diff, matches_played,
rank, note, note_color, logo_url, last_updated
PRIMARY KEY (team_id, league)
```

**season_stats** — aggregated per-player season totals
```
player_id, player_name, team_id, team_name, league, season,
goals, assists, penalties, last_updated
PRIMARY KEY (player_id, league, season)
```

**pipeline_metadata** — producer health tracking
```
key, value, last_updated
```

---

## API Endpoints

```
GET  /                          — Service info
GET  /health                    — DB and cache connectivity
GET  /health/pipeline           — Full pipeline component status (rate limited 10/min)
GET  /games                     — All games, filterable by ?status= and ?league=
GET  /games/{game_id}           — Single game by ID
GET  /games/{game_id}/stats     — Goal events for a specific game
GET  /standings                 — League/group table by ?league=
GET  /leagues                   — List of all competitions with data
POST /chat                      — Natural language query endpoint
WS   /ws                        — WebSocket real-time push
```

---

## Dashboard

A React single-page application with five views and a competition selector:

**Competition Selector** — Switch between Premier League, La Liga, Bundesliga, Serie A, Ligue 1, and the FIFA World Cup. The entire app theme updates to match the selected competition's color scheme.

**Live Scores** — Match cards showing live scores, status badges, team logos, and kickoff times. Updates in real time via WebSocket push. Click any card to view match details.

**League Table / Group Standings** — For club leagues: a full standings table with points, goal difference, and color-coded European qualification and relegation zones. For the World Cup: a grid of group tables showing qualification notes and team logos sourced directly from ESPN.

**Match Detail** — Per-game view with score header, team logos, goal scorers, and a visual goal timeline. For live games the timeline acts as a real-time progress bar with an interpolated clock between API updates. VAR-cancelled goals are automatically removed.

**Ask ScoreStream** — Natural language chat interface powered by Claude. Answers questions about scores, standings, goal scorers, form, and season stats. Generates Recharts visualisations inline for data that suits a chart. Supports follow-up questions via conversation history.

**Pipeline Health** — Internal dashboard showing status of every pipeline component.

---

## Ask ScoreStream (AI Chat)

```
User question
    ↓
Alias expansion (PSG → Paris Saint-Germain, Holland → Netherlands, etc.)
    ↓
Claude — SQL generation (schema + examples + team aliases + World Cup context)
    ↓
PostgreSQL — safe read-only query execution
    ↓
Claude — chart decision (bar / line / pie / text)
    ↓
Claude — answer formatting (natural language + scorer attribution)
    ↓
React — text response + optional inline Recharts visualisation
```

**Example questions:**
- "Who is the top scorer in the Premier League?"
- "Show me the Bundesliga standings as a chart"
- "Who scored in Arsenal's last game?"
- "Which teams have qualified from Group A?"
- "Who has scored the most goals at the World Cup?"
- "Show me PSG's form over their last 5 games"
- "What proportion of goals were penalties in Ligue 1?"
- "Which games went to extra time at the World Cup?"

**Safety measures:**
- Generated SQL checked for forbidden write operations before execution
- Only SELECT statements permitted
- Queries limited to 20 rows maximum
- Truncated SQL detected via `stop_reason` and rejected cleanly

---

## Historical Data

Recent matches (last ~3 weeks) are ingested live via the ESPN producer. Full season historical data is backfilled using the football-data.org API via `backfill_historical.py`:

```bash
# Backfill all 5 leagues for the 2025/26 season
python backfill_historical.py
```

The script maps football-data.org team IDs to ESPN team IDs so logos render correctly for historical games. World Cup data is ingested live via the ESPN producer — no backfill needed.

---

## Project Structure

```
scorestream/
├── docker-compose.yml
├── restart.sh                      # safe restart — clears Spark checkpoints
├── backfill_historical.py          # one-time historical data import
├── sql/
│   └── init.sql
├── producer/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── espn_producer.py            # ESPN API → Kafka (6 competitions)
├── spark/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── streaming_job.py            # PySpark Structured Streaming consumer
├── dags/
│   ├── standings_refresh.py        # 30 min — all leagues + World Cup groups
│   ├── season_stats_refresh.py     # 15 min — aggregates goals into season_stats
│   └── epl_daily_archive.py        # nightly Parquet archive
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                     # FastAPI + WebSocket + /chat AI endpoint
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── public/
│   │   └── index.html
│   └── src/
│       ├── App.jsx                 # Competition selector, themes, WebSocket
│       ├── index.js
│       ├── hooks/
│       │   ├── usePoll.js
│       │   ├── useWebSocket.js
│       │   ├── useNotifications.js
│       │   ├── useSubscriptions.js
│       │   └── useGameWatcher.js
│       └── components/
│           ├── ScoresTab.jsx
│           ├── StandingsTab.jsx    # Club tables + World Cup group grid
│           ├── MatchesTab.jsx
│           ├── PipelineTab.jsx
│           └── ChatTab.jsx         # AI chat + inline Recharts charts
├── checkpoints/
├── archive/
└── README.md
```

---

## Setup

### Prerequisites
- Docker and Docker Compose
- Anthropic API key (for chat feature)

### Environment

Create a `.env` file in the project root:

```bash
ANTHROPIC_API_KEY=your_key_here
DATABASE_URL=postgresql://admin:password@postgres:5432/scorestream
ALLOWED_ORIGINS=http://localhost:3000
FOOTBALL_DATA_API_KEY=your_key_here  # optional, for historical backfill only
```

**Note:** Default PostgreSQL credentials in `docker-compose.yml` are intentional for local development. Never use these in production.

### Start

```bash
docker compose up --build
```

Open the dashboard at `http://localhost:3000`.

The Pipeline Health tab is the fastest way to verify all components are healthy after startup.

### Restart safely

```bash
./restart.sh
```

Clears Spark checkpoints and restarts all services cleanly.

### Backfill historical data (optional)

```bash
python backfill_historical.py
```

Populates the full season's games for all 5 club leagues using football-data.org. Requires `FOOTBALL_DATA_API_KEY` in `.env`.

---

## Engineering Challenges

**Real-time clock interpolation** — ESPN's public API updates its clock roughly every 60 seconds. The match detail view interpolates between server updates using a `setInterval` ticker, resetting to the confirmed server value on each poll. Two separate state variables keep the display clock (ticking every second) and bar position (updating on confirmed data only) independent.

**Goal deduplication** — ESPN sometimes refines goal types after the initial event is published (e.g. `"Goal"` → `"Goal - Header"`). A `UNIQUE (game_id, player_id, seconds)` constraint combined with `ON CONFLICT DO UPDATE SET goal_type` handles this cleanly — the row is updated in place rather than duplicated. VAR cancellations are handled by a delete-before-upsert pattern in Spark that removes any goals no longer present in ESPN's details array.

**Multi-competition pipeline** — Extending from a single EPL feed to six competitions (five club leagues plus the World Cup) required generalising every layer. The producer loops over a `LEAGUES` dict, Kafka topics were renamed from `epl.*` to `sports.*`, and the database schema added a `league` column throughout. The standings table gained `group_name`, `note`, `note_color`, and `logo_url` columns to support World Cup group stage data. No structural changes to Kafka or Spark were required.

**WebSocket real-time push** — Replaced frontend polling with a Redis pub/sub → WebSocket push architecture. Spark publishes a lightweight notification to Redis after each batch commit. FastAPI's async Redis subscriber broadcasts to all connected WebSocket clients. The frontend triggers targeted refetches on receiving the push, reducing API load during quiet periods while ensuring near-instant updates during live matches.

**Text-to-SQL natural language chat** — A two-step Claude pipeline converts natural language questions into PostgreSQL queries. The first call generates safe read-only SQL using schema context, example queries, team alias mappings, and World Cup-specific context. The second call formats raw database rows into readable natural language with correct goal attribution using `CASE WHEN team_id = home_id`. A third step decides whether results are better shown as a Recharts bar, line, or pie chart. Conversation history is passed with each request enabling contextual follow-up questions.

**Historical data backfill** — ESPN's public API only retains scoreboard data for ~3 weeks. Full season historical data is backfilled via football-data.org's API with a one-time script that maps football-data.org team IDs to ESPN team IDs so logos render correctly for historical games.

**Logo resolution across data sources** — ESPN team IDs and football-data.org team IDs are completely different numbering systems. A manually curated mapping of 96 teams across all five leagues ensures logos load correctly regardless of which source the game data came from. World Cup national team logos use ESPN's country CDN path with a two-attempt fallback pattern to avoid infinite re-render loops.

---

## What's Next (Phase 5)

- Replace local Kafka with AWS MSK
- Replace local Spark with AWS Glue managed jobs
- Replace local Parquet storage with S3
- Deploy FastAPI on EC2 behind an Application Load Balancer
- Deploy frontend on S3 + CloudFront
- Add CloudWatch monitoring and alerting
- Stream chat responses via WebSocket for faster perceived response time
- Add historical analytics tab using archived Parquet data via DuckDB
- Expand chat to support chart generation for World Cup bracket visualisation