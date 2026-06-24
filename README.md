# ScoreStream

A real-time football data pipeline built with Kafka, PySpark Structured Streaming, Apache Airflow, PostgreSQL, and FastAPI — containerized end-to-end with Docker Compose.

ScoreStream ingests live match data from **5 major European leagues and the FIFA World Cup** via the ESPN public API, streams events through Kafka, processes them with PySpark in real time, and serves the results via a REST API with Redis caching and WebSocket push. A parallel Airflow batch layer handles scheduled standings refreshes, season stats aggregation, and daily Parquet archiving. A natural language chat interface powered by Claude — with streamed, real-time responses over WebSocket — allows users to query live pipeline data in plain English and receive both text answers and dynamically generated charts.

---

## Architecture

```
ESPN Public API (polled every 30s — 6 competitions)
        │
        ▼
Python Producer
        │  publishes to Kafka topics
        ▼
┌─────────────────────────────────────┐
│  sports.live.scores (3 partitions)  │  game state + goal events
│  sports.standings   (1 partition)   │  league/group table snapshots
└─────────────────────────────────────┘
        │
        ▼
PySpark Structured Streaming
  ├── process_games     →  games table       (upsert, every 5s)
  └── process_goals     →  goals table       (delete-then-upsert keyed on game_id + team_id + seconds,
                                              so ESPN goal-scorer corrections update in place rather than creating duplicates)
        │
        ▼
PostgreSQL ←→ Redis (dynamic TTL)
        │          │
        │          └──▶ Redis pub/sub → WebSocket push → React frontend
        ▼
FastAPI REST API + WebSocket (/ws, /ws/chat)

Airflow (parallel batch layer)
  ├── standings_refresh    →  every 30 min, all 6 competitions, removes
  │                            relegated/dropped teams automatically
  └── daily_archive    →  nightly Parquet snapshots to ./archive/

Claude AI Chat (/ws/chat — streamed over WebSocket)
  ├── SQL generation       →  natural language → PostgreSQL query
  ├── Query execution      →  safe read-only execution
  ├── Chart detection      →  decides bar/line/pie or text-only response
  └── Answer streaming     →  token-by-token response via Claude's streaming API,
                               pushed live to the frontend as it's generated
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
| FIFA World Cup | fifa.world | 48 | National (group stage + knockout) |

Standings automatically drop relegated/eliminated teams each refresh cycle — the Airflow DAG deletes any team no longer present in ESPN's current response for a given league/season, so promoted and relegated teams stay in sync across season boundaries without manual cleanup.

---

## Services

| Service | Port | Description |
|---|---|---|
| FastAPI | 8000 | REST API + WebSocket (`/ws`) + streamed AI chat (`/ws/chat`) |
| Frontend | 3000 | React dashboard UI |
| Airflow | 8081 | Pipeline orchestration UI |
| Kafka UI | 8090 | Topic and message inspection |
| PostgreSQL | 5432 | Primary database |
| Redis | 6379 | API response cache + pub/sub broker |

---

## Database Schema

**games**
```
game_id, league, home_team, away_team, home_team_name, away_team_name,
home_id, away_id, home_logo, away_logo, home_score, away_score,
status, status_detail, period, clock, start_time (TIMESTAMPTZ), last_updated
```

**goals**
```
id, game_id, league, player_id, player_name, team_id,
minute, seconds (FLOAT), goal_type, own_goal, penalty_goal, created_at
UNIQUE (game_id, team_id, seconds)
```
The unique constraint is keyed on `team_id` rather than `player_id` — ESPN occasionally reassigns which player is credited for a goal scored at a fixed moment (most commonly own-goal corrections), and the team + timing is the stable identity of the event, not the player attribution. Spark's delete-then-upsert step removes any goal whose `(team_id, seconds)` no longer appears in ESPN's current payload before re-inserting, so corrections update in place instead of producing duplicate rows.

**standings**
```
team_id, league, season, team_name, group_name, wins, draws, losses,
points, goals_for, goals_against, goal_diff, matches_played,
rank, deductions, note, note_color, logo_url, last_updated
PRIMARY KEY (team_id, league, season)
```
`group_name`, `note`, and `note_color` support World Cup group-stage display (qualification status text and color sourced directly from ESPN). `logo_url` stores ESPN's CDN URL directly per team, avoiding the need to maintain a manual team-ID-to-logo mapping for every data source.

**season_stats**
```
player_id, player_name, team_id, team_name, league, season,
goals, assists, penalties, last_updated
PRIMARY KEY (player_id, league, season)
```

**pipeline_metadata**
```
key, value, last_updated
```

---

## API Endpoints

```
GET   /                          — Service info
GET   /health                    — DB and cache connectivity
GET   /health/pipeline           — Full pipeline component status (rate limited 10/min)
GET   /games                     — All games, filterable by ?status=, ?league=, ?window=
GET   /games/{game_id}           — Single game by ID
GET   /games/{game_id}/stats     — Goal events for a specific game
GET   /standings                 — League/group table by ?league=
GET   /leagues                   — List of all competitions with data
POST  /chat                      — Natural language query endpoint (non-streamed, legacy)
WS    /ws                        — WebSocket real-time score/standings push
WS    /ws/chat                   — Streamed natural language chat (token-by-token)
```

---

## Dashboard

A React single-page application with five views, a competition selector, and per-league theming:

**Competition Selector** — Switch between Premier League, La Liga, Bundesliga, Serie A, Ligue 1, and the FIFA World Cup. The entire app's color scheme (header, nav, cards, charts) updates to match the selected competition, including a dedicated background shade derived from each league's primary color.

**Live Scores** — Match cards grouped by date (Today / Tomorrow / Yesterday / full date), sorted with live games first within each day. Dates are computed in UTC to avoid the day-boundary bugs that arise from late-evening Eastern Time kickoffs. On load, the page automatically scrolls to today's matches if any exist. Updates in real time via WebSocket push.

**League Table / Group Standings** — For club leagues: a full standings table with points, goal difference, and color-coded UEFA qualification and relegation zones (calculated per-league, since cutoffs differ across competitions). For the World Cup: a responsive grid of group tables showing ESPN's live qualification notes and team logos. Rendered using semantic `<table>` markup so columns size correctly regardless of team name length.

**Match Detail** — Per-game view with score header, team logos, goal scorers (correctly attributed even after ESPN reassigns a scorer), and a visual goal timeline. For live games the timeline acts as a real-time progress bar with a clock that interpolates between 30-second API updates rather than jumping discretely. VAR-cancelled goals are automatically removed from the timeline and scorer list.

**Ask ScoreStream** — Natural language chat interface powered by Claude, with responses streamed token-by-token over a dedicated WebSocket connection for near-instant perceived response time. Generates Recharts visualizations inline for data that suits a chart, with a "show query" toggle revealing the generated SQL for transparency. Supports follow-up questions via conversation history.

**Pipeline Health** — Internal dashboard showing status of every pipeline component.

---

## Ask ScoreStream (AI Chat)

```
User question (sent over WebSocket)
    ↓
Alias expansion (PSG → Paris Saint-Germain, Holland → Netherlands, etc.)
    ↓
Claude — SQL generation (schema + examples + team aliases + World Cup context)
    ↓
PostgreSQL — safe read-only query execution
    ↓
Claude — chart decision (bar / line / pie / text-only)
    ↓
Claude — STREAMED answer generation, pushed to the client chunk-by-chunk
    ↓
React — text renders live as it streams in; chart + "show query" appear once complete
```

**Example questions:**
- "Who is the top scorer in the Premier League?"
- "Show me the Bundesliga standings as a chart"
- "Who scored in Arsenal's last game?"
- "Which teams have qualified from Group A?"
- "Has anyone scored a penalty at the World Cup?"
- "Show me PSG's form over their last 5 games"
- "What proportion of goals were open play vs penalties vs own goals in Ligue 1?"
- "Which games went to extra time at the World Cup?"

**Architecture notes:**
- The SQL-generation, query-execution, and chart-decision steps run sequentially but quickly (a few seconds total); only the final answer-formatting step is streamed, since it's the only inherently sequential, token-by-token part of the pipeline
- The schema explicitly documents *derived* categories (e.g. "open play" = `own_goal = false AND penalty_goal = false`) so Claude doesn't report data as "unavailable" when it's actually computable from existing boolean flags
- "How many" and "are there any" style questions are pushed toward `COUNT(*)` queries so a zero result is a real, single-row answer rather than an empty result set that triggers a generic fallback message
- Chart responses are parsed defensively: markdown code fences are stripped via regex, `x_key`/`y_key` field names are normalized across multiple naming variations Claude might use, and any mismatched key is auto-corrected by inspecting the actual data's field types

**Safety measures:**
- Generated SQL checked for forbidden write operations before execution
- Only SELECT statements permitted
- Queries limited to 20 rows maximum
- Truncated SQL detected via `stop_reason` and rejected cleanly

---

## Historical Data

Recent matches (last ~3 weeks) are ingested live via the ESPN producer, which only retains scoreboard data for a limited window. Full season historical data is backfilled using the football-data.org API via `backfill_historical.py`:

```bash
python backfill_historical.py
```

The script maps football-data.org team IDs to ESPN team IDs (a manually curated mapping of 96+ teams across all five leagues) so logos render correctly for historical games regardless of which data source populated them. World Cup data is ingested entirely live via the ESPN producer — no backfill needed, since the tournament window falls within ESPN's retention period.

---

## Project Structure

```
scorestream/
├── docker-compose.yml
├── restart.sh                      # safe restart — clears Spark checkpoints (incl. hidden files)
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
│   ├── standings_refresh.py        # 30 min — all leagues + World Cup groups,
│   │                                 removes relegated/dropped teams
│   ├── season_stats_refresh.py     # 15 min — aggregates goals into season_stats
│   └── epl_daily_archive.py        # nightly Parquet archive
├── api/
│   ├── Dockerfile
│   ├── requirements.txt
│   └── main.py                     # FastAPI + WebSocket + streamed /ws/chat AI endpoint
├── frontend/
│   ├── Dockerfile
│   ├── package.json
│   ├── public/
│   │   └── index.html
│   └── src/
│       ├── App.jsx                 # Competition selector, per-league themes,
│       │                             sticky header/nav, WebSocket indicator
│       ├── index.js
│       ├── hooks/
│       │   ├── usePoll.js
│       │   ├── useWebSocket.js     # scores/standings push (/ws)
│       │   ├── useChatWebSocket.js # streamed chat push (/ws/chat)
│       │   ├── useNotifications.js
│       │   ├── useSubscriptions.js
│       │   └── useGameWatcher.js
│       └── components/
│           ├── ScoresTab.jsx       # date-grouped (UTC-correct), auto-scroll to Today
│           ├── StandingsTab.jsx    # table-based layout, club + World Cup group grid
│           ├── MatchesTab.jsx
│           ├── PipelineTab.jsx
│           └── ChatTab.jsx         # streamed AI chat + inline Recharts charts
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

In `docker-compose.yml`, the frontend needs two distinct WebSocket URLs since chat and live scores use separate connections:

```yaml
frontend:
    environment:
      REACT_APP_API_URL:      http://localhost:8000
      REACT_APP_WS_URL:       ws://localhost:8000/ws
      REACT_APP_CHAT_WS_URL:  ws://localhost:8000/ws/chat
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

Clears Spark checkpoints (including hidden metadata files, which a plain `rm -rf *` misses on macOS) and restarts all services cleanly.

### Backfill historical data (optional)

```bash
python backfill_historical.py
```

Populates the full season's games for all 5 club leagues using football-data.org. Requires `FOOTBALL_DATA_API_KEY` in `.env`.

---

## Engineering Challenges

**Real-time clock interpolation** — ESPN's public API updates its clock roughly every 60 seconds. The match detail view interpolates between server updates using a `setInterval` ticker, resetting to the confirmed server value on each poll, with separate state for the display clock (ticks every second) and the progress bar position (updates only on confirmed data) to avoid the bar racing ahead of the actual match state.

**Goal correction handling** — ESPN periodically refines published goal data after the fact: refining a goal's type (`"Goal"` → `"Goal - Header"`), reassigning which player is credited (notably for own-goal corrections), and occasionally retracting a goal entirely (VAR overturns). A unique constraint on `(game_id, team_id, seconds)` combined with a delete-then-upsert pattern in Spark — deleting any goal no longer present in ESPN's current payload before re-inserting current goals — means all three correction types resolve cleanly without manual cleanup or duplicate rows.

**UTC-correct date grouping** — Grouping live scores by calendar day initially misplaced late-evening matches (9-10pm local kickoffs land after midnight UTC) into the wrong day's section. The fix normalizes every timestamp to a plain `YYYY-MM-DD` UTC date string via `toISOString().slice(0, 10)` before comparison, sidestepping locale-dependent `Date` parsing inconsistencies entirely, combined with switching the `start_time` column to `TIMESTAMPTZ` so PostgreSQL and JavaScript agree on what a timestamp actually represents.

**Multi-competition pipeline** — Extending from a single EPL feed to six competitions (five club leagues plus the World Cup) required generalizing every layer: the producer loops over a `LEAGUES` dict, Kafka topics were renamed from `epl.*` to `sports.*`, and `league` was threaded through every table. The standings table gained `group_name`, `note`, `note_color`, and `logo_url` to support World Cup group-stage display, plus a `season` column with the primary key extended to `(team_id, league, season)` so relegated/dropped teams are automatically removed each refresh cycle rather than persisting as stale rows across season boundaries.

**Streamed AI chat over WebSocket** — The original `/chat` REST endpoint required the full multi-step Claude pipeline (SQL generation, query execution, chart decision, answer formatting) to complete before any response reached the user. Moving the final answer-formatting step onto a dedicated `/ws/chat` WebSocket endpoint and using Claude's streaming API (`messages.stream()` with `stream.text_stream`) lets the response render token-by-token as it's generated, while the upstream steps (which must complete sequentially regardless) still run synchronously before streaming begins. This required a separate WebSocket connection and environment variable from the existing live-scores `/ws` socket, since the frontend's two real-time hooks (`useWebSocket` and `useChatWebSocket`) would otherwise silently share — and collide on — the same connection URL.

**Text-to-SQL with derived-category awareness** — A two-step Claude pipeline converts natural language into PostgreSQL queries, but several real football questions ("open play vs penalty vs own goal", "did anyone score at all") map to *derived* values rather than stored columns. The schema documentation and example queries explicitly spell out how to compute these (`CASE WHEN own_goal THEN ... WHEN penalty_goal THEN ... ELSE 'Open Play' END`, and steering toward `COUNT(*)` so a zero-result answer is distinguishable from a query that found nothing at all) — without this, Claude correctly but unhelpfully reported the data as "unavailable."

**Historical data backfill across mismatched ID systems** — ESPN's public API only retains ~3 weeks of scoreboard history. Football-data.org fills the gap for full-season historical data, but its team IDs are a completely separate numbering system from ESPN's. A manually curated mapping of 96+ teams (cross-referenced by querying ESPN's live scoreboard across a 30-day window to capture confirmed IDs) ensures historical games display the same logos as live ones, avoiding the broken/mismatched-team-logo bugs that a naive ID pass-through produced.

---

## What's Next (Phase 5)

- Replace local Kafka with AWS MSK
- Replace local Spark with AWS Glue managed jobs
- Replace local Parquet storage with S3
- Deploy FastAPI on EC2 behind an Application Load Balancer
- Deploy frontend on S3 + CloudFront
- Add CloudWatch monitoring and alerting
- Migrate the legacy `/chat` REST endpoint fully to `/ws/chat`, removing the non-streamed code path
- Add historical analytics using archived Parquet data via DuckDB
- Add assist tracking once a reliable ESPN field is identified