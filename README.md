# ScoreStream

A real-time football data pipeline built with Kafka, PySpark Structured Streaming, Apache Airflow, PostgreSQL, and FastAPI — containerized end-to-end with Docker Compose for local development and deployed to AWS using CDK.

ScoreStream ingests live match data from **5 major European leagues and the MLS (Major League Soccer)** via the ESPN public API, streams events through Kafka, processes them with PySpark in real time, and serves the results via a REST API with Redis caching and WebSocket push. A parallel batch layer handles scheduled standings refreshes, season stats aggregation, and daily Parquet archiving. A natural language chat interface powered by Claude — with streamed, real-time responses over WebSocket — allows users to query live pipeline data in plain English and receive both text answers and dynamically generated charts.

---

## Architecture

### Local Development

```
ESPN Public API (polled every 30s — 6 competitions)
        │
        ▼
Python Producer
        │  publishes to Kafka topic
        ▼
┌─────────────────────────────────────┐
│  sports.live.scores (2 partitions)  │  game state + goal events
└─────────────────────────────────────┘
        │
        ▼
PySpark Structured Streaming
  ├── process_games     →  games table       (upsert, every 5s)
  └── process_goals →  goals table   (delete-then-upsert keyed on game_id + team_id + seconds)
        │
        ▼
PostgreSQL ←→ Redis (dynamic TTL)
        │          │
        │          └──▶ Redis pub/sub → WebSocket push → React frontend
        ▼
FastAPI REST API + WebSocket (/ws, /ws/chat)

Airflow (batch layer)
  ├── standings_refresh    →  every 30 min, all 6 competitions
  ├── season_stats_refresh →  every 15 min
  └── epl_daily_archive    →  nightly Parquet snapshots

Claude AI Chat (/ws/chat — streamed over WebSocket)
  ├── SQL generation       →  natural language → PostgreSQL query
  ├── Query execution      →  safe read-only execution
  ├── Chart detection      →  bar / line / pie or text-only
  └── Answer streaming     →  token-by-token via Claude streaming API
```

### AWS Production

```
Users
  ↓ HTTPS
CloudFront → S3 (React frontend)
  ↓ HTTP
ALB → FastAPI (ECS Fargate, private subnet)
         ↓                    ↓
    RDS PostgreSQL      ElastiCache Redis
         ↑
    AWS Glue Streaming ←── Amazon MSK ←── Producer (ECS Fargate) ←── ESPN API

EventBridge Scheduler → Fargate tasks (standings refresh, daily archive)
                                ↓
                          RDS + S3

CloudWatch Dashboard + Alarms → SNS → Email
```

---

## AWS Infrastructure (CDK)

The entire AWS infrastructure is defined as code using AWS CDK (Python) in the `infra/` directory. The stack is organized into six independent deployable units:

| Stack           | Resources                                                                                                   |
| --------------- | ----------------------------------------------------------------------------------------------------------- |
| NetworkStack    | VPC, public/private subnets, NAT gateway, security groups, Secrets Manager                                  |
| DataStack       | RDS PostgreSQL, ElastiCache Redis, S3 (Glue scripts and checkpoints)                                        |
| MskStack        | Amazon MSK Kafka cluster with IAM authentication                                                            |
| ComputeStack    | ECS cluster, producer service, Glue streaming job, API service, ALB, scheduler tasks, EventBridge schedules |
| EdgeStack       | S3 (frontend), CloudFront distribution with OAC                                                             |
| MonitoringStack | CloudWatch dashboard, alarms, SNS topic                                                                     |

Deploy all stacks:

```bash
cd infra
pip install -r requirements.txt
cdk deploy --all
```

Tear down:

```bash
cdk destroy --all
```

---

## Supported Competitions

| Competition    | ESPN Code | Teams | Type |
| -------------- | --------- | ----- | ---- |
| Premier League | eng.1     | 20    | Club |
| La Liga        | esp.1     | 20    | Club |
| Bundesliga     | ger.1     | 18    | Club |
| Serie A        | ita.1     | 20    | Club |
| Ligue 1        | fra.1     | 20    | Club |
| MLS            | usa.1     | 29    | Club |

---

## Local Services

| Service    | Port | Description                             |
| ---------- | ---- | --------------------------------------- |
| FastAPI    | 8000 | REST API + WebSocket + streamed AI chat |
| Frontend   | 3000 | React dashboard                         |
| Airflow    | 8081 | Pipeline orchestration                  |
| Kafka UI   | 8090 | Topic inspection                        |
| PostgreSQL | 5432 | Primary database                        |
| Redis      | 6379 | Cache + pub/sub                         |

---

## Database Schema

**games**

```
game_id, league, home_team, away_team, home_team_name, away_team_name,
home_id, away_id, home_logo, away_logo, home_score, away_score,
shootout_home, shootout_away, status, status_detail, period, clock,
start_time (TIMESTAMPTZ), round, last_updated
```

**goals**

```
id, game_id, league, player_id, player_name, team_id,
minute, seconds (FLOAT), goal_type, own_goal, penalty_goal, created_at
UNIQUE (game_id, team_id, seconds)
```

The unique constraint is keyed on `team_id` rather than `player_id` — ESPN occasionally reassigns which player is credited for a goal (most commonly own-goal corrections), and the team + timing is the stable identity of the event. Spark's delete-then-upsert removes any goal no longer present in ESPN's current payload before re-inserting, so corrections update in place without producing duplicates. Penalty shootout kicks are filtered out in the producer using a combination of ESPN's `shootout` flag and a defensive clock-value check (≥7200 seconds in a penalties-final status game).

**standings**

```
team_id, league, season, team_name, group_name, wins, draws, losses,
points, goals_for, goals_against, goal_diff, matches_played,
rank, deductions, note, note_color, logo_url, last_updated
PRIMARY KEY (team_id, league, season)
```

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
GET   /health/pipeline           — Pipeline component status
GET   /games                     — Games, filterable by ?status=, ?league=, ?window=
GET   /games/{game_id}           — Single game
GET   /games/{game_id}/stats     — Goal events for a game
GET   /standings                 — League/group table by ?league=
GET   /leagues                   — All competitions with data
POST  /chat                      — Natural language query (legacy)
WS    /ws                        — Real-time score/standings push
WS    /ws/chat                   — Streamed AI chat
```

---

## Dashboard

A React single-page application with six views and per-competition theming:

**Scores** — Match cards grouped by Eastern Time date (Today / Tomorrow / Yesterday / full date), live games sorted first within each day. Auto-scrolls to today's matches on load. Updates via WebSocket push.

**Standings** — Club leagues: full table with points, goal difference, color-coded UEFA qualification and relegation zones.

**Match Detail** — Score header with shootout scores when applicable, goal scorers correctly attributed after ESPN corrections, visual goal timeline with dynamic duration for extra time games. Live games show an interpolated clock that ticks between 30-second API updates.

**Ask ScoreStream** — Natural language chat powered by Claude, streamed token-by-token over a dedicated WebSocket. Generates Recharts visualizations inline. Supports follow-up questions via conversation history. "Show query" toggle reveals the generated SQL.

**Pipeline Health** — Internal dashboard showing status of every pipeline component.

---

## Ask ScoreStream (AI Chat)

```
User question (WebSocket)
    ↓
Alias expansion (PSG → Paris Saint-Germain, Holland → Netherlands, etc.)
    ↓
Claude — SQL generation (schema + examples + team aliases + MLS context)
    ↓
PostgreSQL — safe read-only execution
    ↓
Claude — chart decision (bar / line / pie / text-only)
    ↓
Claude — STREAMED answer, pushed token-by-token to the frontend
    ↓
React — text renders live; chart + SQL toggle appear on completion
```

**Example questions:**

- "Who is the top scorer in the Premier League?"
- "Show me the Bundesliga standings as a chart"
- "Who scored in Arsenal's last game?"
- "What proportion of goals were open play vs penalties in Ligue 1?"
- "Show me PSG's form over their last 5 games"

**Safety measures:**

- Generated SQL checked for write operations before execution
- Only SELECT statements permitted
- Queries limited to 20 rows
- Truncated SQL detected via `stop_reason` and rejected

---

## Historical Data

ESPN retains ~3 weeks of scoreboard history. Full season historical data is backfilled via football-data.org:

```bash
python backfill_historical.py
```

A manually curated mapping of 96+ teams ensures ESPN team IDs are used for historical games so logos render correctly.

---

## Project Structure

```
scorestream/
├── docker-compose.yml
├── restart.sh
├── backfill_historical.py
├── sql/
│   └── init.sql
├── producer/
│   └── espn_producer.py            # ESPN → Kafka (6 competitions)
├── spark/
│   ├── streaming_job.py            # Local PySpark consumer
│   └── streaming_job_aws.py        # AWS Glue streaming consumer
├── scheduler/
│   ├── Dockerfile
│   ├── entrypoint.sh               # Routes SCHEDULER_JOB env var to script
│   ├── refresh_standings.py
│   ├── refresh_season_stats.py
│   └── archive_daily.py
├── dags/
│   ├── standings_refresh.py
│   ├── season_stats_refresh.py
│   └── epl_daily_archive.py
├── api/
│   └── main.py                     # FastAPI + WebSocket + /ws/chat
├── frontend/
│   └── src/
│       ├── App.jsx
│       ├── hooks/
│       │   ├── useWebSocket.js
│       │   ├── useChatWebSocket.js
│       │   ├── useNotifications.js
│       │   ├── useSubscriptions.js
│       │   └── useGameWatcher.js
│       └── components/
│           ├── ScoresTab.jsx
│           ├── StandingsTab.jsx
│           ├── BracketTab.jsx
│           ├── MatchesTab.jsx
│           ├── PipelineTab.jsx
│           └── ChatTab.jsx
├── infra/                          # AWS CDK (Python)
│   ├── app.py
│   ├── network_stack.py
│   ├── data_stack.py
│   ├── msk_stack.py
│   ├── compute_stack.py
│   ├── edge_stack.py
│   └── monitoring_stack.py
├── checkpoints/
├── archive/
└── README.md
```

---

## Local Setup

### Prerequisites

- Docker and Docker Compose
- Anthropic API key

### Environment

Create `.env` in the project root:

```bash
ANTHROPIC_API_KEY=your_key_here
DATABASE_URL=postgresql://admin:password@postgres:5432/scorestream
ALLOWED_ORIGINS=http://localhost:3000
FOOTBALL_DATA_API_KEY=your_key_here  # optional, backfill only
```

`docker-compose.yml` frontend environment:

```yaml
REACT_APP_API_URL: http://localhost:8000
REACT_APP_WS_URL: ws://localhost:8000/ws
REACT_APP_CHAT_WS_URL: ws://localhost:8000/ws/chat
```

### Start

```bash
docker compose up --build
```

Dashboard at `http://localhost:3000`. Check Pipeline Health to verify all components.

### Restart safely

```bash
./restart.sh
```

Clears Spark checkpoints (including hidden files) and restarts all services.

### Backfill historical data

```bash
python backfill_historical.py
```

---

## AWS Setup

### Prerequisites

- AWS account and CLI configured
- Node (for CDK CLI): `npm install -g aws-cdk`
- CDK bootstrapped: `cdk bootstrap aws://ACCOUNT_ID/us-east-1`

### Deploy

```bash
cd infra
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Build and push container images to ECR first
# (see infra/README.md for image build commands)

cdk deploy --all
```

### Secrets

After deploy, set secret values:

```bash
aws secretsmanager put-secret-value \
    --secret-id "scorestream/anthropic-api-key" \
    --secret-string "your-key"

aws secretsmanager put-secret-value \
    --secret-id "scorestream/football-data-api-key" \
    --secret-string "your-key"
```

RDS credentials are generated and managed automatically by RDS.

### Tear down

```bash
cdk destroy --all
```

---

## Engineering Challenges

**Real-time clock interpolation** — ESPN updates its match clock roughly every 60 seconds. The match detail view interpolates between updates using `setInterval`, resetting on each confirmed server value, with separate state for the display clock and the progress bar to avoid the bar racing ahead of actual match time.

**Goal correction handling** — ESPN refines published goal data after the fact: changing goal type, reassigning scorer credit, or retracting goals via VAR. A unique constraint on `(game_id, team_id, seconds)` combined with delete-then-upsert in Spark handles all three cases. Penalty shootout kicks are filtered using ESPN's `shootout` flag with a defensive fallback on clock value (≥7200s in STATUS_FINAL_PEN games) since the flag is sometimes absent on late-corrected kicks.

**UTC-correct date grouping** — Late-evening kickoffs (9-10pm EDT) cross midnight UTC and land on the next calendar day. All date grouping uses Eastern Time via `toLocaleDateString('en-US', { timeZone: 'America/New_York' })`, and the backend window filter uses PostgreSQL's AT TIME ZONE conversion to anchor boundaries to Eastern midnight rather than UTC midnight.

**Multi-competition pipeline** — Extending from EPL to six competitions required generalizing every layer: LEAGUES dict in the producer, renamed Kafka topics (epl._ → sports._), league column throughout the schema, group_name/note/note_color/logo_url on standings.

**Streamed AI chat** — Moving from a blocking HTTP POST to a WebSocket-streamed response required structuring the pipeline so SQL generation, query execution, and chart detection run synchronously first, then the answer-formatting step streams token-by-token. Two separate WebSocket connections (useWebSocket for scores, useChatWebSocket for chat) use distinct environment variables to prevent the silent URL-collision bug where both hooks read the same env var and connect to the wrong endpoint.

**Text-to-SQL with derived-category awareness** — Several football questions map to derived values: "open play" is `own_goal = false AND penalty_goal = false`, zero goals is a COUNT of 0 not an empty result set. Schema documentation and example queries explicitly spell out these derivations so Claude doesn't report available data as missing.

**AWS architecture decisions** — EventBridge-scheduled Fargate tasks replace MWAA (managed Airflow) as the batch layer — the three scheduled jobs run for seconds every 15-30 minutes, making MWAA's $354/month minimum unjustifiable. The same Airflow DAG logic runs as standalone Python scripts selected by a SCHEDULER_JOB environment variable at container startup. MSK with IAM authentication replaces local Kafka — no credential management beyond the task role, and the aws-msk-iam-sasl-signer library generates short-lived tokens automatically from the Fargate task's IAM role. Glue streaming with S3 checkpoints replaces the local Spark container, eliminating cluster management while keeping the same PySpark Structured Streaming API.

**Historical data backfill** — ESPN retains only ~3 weeks of scoreboard history. Football-data.org fills the gap for full-season data, but uses a completely different team ID numbering system. A manually curated mapping of 96+ teams cross-referenced by querying ESPN's live scoreboard across 30 days ensures historical games display correct logos regardless of which source populated them.

---

## What's Next

- Stream chat responses immediately on SQL completion rather than waiting for chart detection
- Historical analytics tab using archived Parquet data via DuckDB
- Assist tracking once a reliable ESPN field is confirmed
- Production hardening: Multi-AZ RDS, MSK replication factor 3, WAF on ALB
- CI/CD pipeline: GitHub Actions building and pushing images on merge, CDK deploy on tag
