# ScoreStream

A real-time sports data pipeline and analytics platform built with Kafka, PySpark Structured Streaming, PostgreSQL, and FastAPI — containerized end-to-end with Docker Compose for local development and deployed to AWS using CDK. An analytics layer powered by Snowflake and dbt sits on top of the operational pipeline, exposing mart tables through dedicated API endpoints.

ScoreStream ingests live match data from **5 major European leagues and the MLS (Major League Soccer)** via the ESPN public API, streams events through Kafka, processes them with PySpark in real time, and serves the results via a REST API with Redis caching and WebSocket push. A parallel batch layer handles scheduled standings refreshes, season stats aggregation, and daily Parquet archiving to S3 — which feeds a nightly Snowflake load and dbt model refresh. A natural language chat interface powered by Claude — with streamed, real-time responses over WebSocket — allows users to query live pipeline data in plain English and receive both text answers and dynamically generated charts.

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
  ├── process_games  →  games table  (upsert, every 5s)
  └── process_goals  →  goals table  (delete-then-upsert keyed on game_id + team_id + seconds)
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
  └── archive_daily        →  nightly Parquet snapshots → S3
```

### AWS Production

```
Users
  ↓ HTTPS
CloudFront → S3 (React frontend)
  ↓ HTTP
ALB → FastAPI (ECS Fargate, private subnet)
         ↓                    ↓                   ↓
    RDS PostgreSQL      ElastiCache Redis    Snowflake (analytics)
         ↑
    AWS Glue Streaming ←── Amazon MSK ←── Producer (ECS Fargate) ←── ESPN API

EventBridge Scheduler → Fargate tasks (standings refresh, daily archive)
                                ↓
                          RDS + S3 (Parquet)
                                ↓
                         Snowflake RAW schema
                                ↓
                          dbt (staging → marts)
                                ↓
                     FastAPI /analytics/* endpoints

CloudWatch Dashboard + Alarms → SNS → Email
```

### Analytics Layer (Snowflake + dbt)

```
S3 (nightly Parquet archive)
        │
        ▼  external stage + COPY INTO
Snowflake RAW schema
  ├── games
  ├── goals
  ├── standings
  └── season_stats
        │
        ▼  dbt run
Snowflake STAGING schema
  ├── stg_scorestream__games
  ├── stg_scorestream__goals
  ├── stg_scorestream__standings
  └── stg_scorestream__season_stats
        │
        ▼  dbt run
Snowflake MARTS schema
  ├── fct_goals          — goal events enriched with game context
  ├── fct_games          — completed matches with derived metrics
  ├── dim_teams          — current standings snapshot per team
  ├── mart_player_stats  — current season top scorers across all leagues
  └── mart_league_summary — aggregate match and goal metrics per competition
```

---

## AWS Infrastructure (CDK)

The entire AWS infrastructure is defined as code using AWS CDK (Python) in the `infra/` directory. The stack is organized into seven independent deployable units:

| Stack           | Resources                                                                                                    |
| --------------- | ------------------------------------------------------------------------------------------------------------ |
| NetworkStack    | VPC, public/private subnets, NAT gateway, security groups, Secrets Manager references                        |
| RdsStack        | RDS PostgreSQL — permanent stack, never destroyed, `RemovalPolicy.RETAIN`                                    |
| DataStack       | ElastiCache Redis, S3 (Glue scripts, checkpoints, Parquet archive)                                           |
| MskStack        | Amazon MSK Kafka cluster with IAM authentication                                                             |
| ComputeStack    | ECS cluster, producer service, Glue streaming job, API service, ALB, scheduler tasks, EventBridge schedules  |
| EdgeStack       | S3 (frontend), CloudFront distribution with OAC                                                              |
| MonitoringStack | CloudWatch dashboard, alarms, SNS topic                                                                      |

**Teardown** (RdsStack and NetworkStack always stay up):

```bash
# 1 — set nat_gateways=0 in network_stack.py
cdk destroy MonitoringStack --force
cdk destroy EdgeStack --force
cdk destroy ComputeStack --force
cdk destroy MskStack --force
cdk destroy DataStack --force
cdk deploy NetworkStack   # removes NAT gateway, keeps VPC/subnets/SGs
```

**Restart**:

```bash
# 1 — set nat_gateways=1 in network_stack.py
cdk deploy NetworkStack
cdk deploy DataStack
cdk deploy MskStack
aws s3 cp spark/streaming_job_aws.py s3://scorestream-glue-ACCOUNT/scripts/streaming_job.py
cdk deploy ComputeStack
# rebuild frontend with new CloudFront domain
cdk deploy EdgeStack
cdk deploy MonitoringStack
aws glue start-job-run --job-name scorestream-streaming
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

## Snowflake Schema (dbt)

The dbt project lives in `scorestream_dbt/` and follows a standard three-layer architecture.

**RAW** — direct mirror of nightly Parquet archives loaded via S3 external stage. One table per operational source: `games`, `goals`, `standings`, `season_stats`.

**STAGING** — light cleaning and type casting on top of RAW. Renames columns to consistent conventions, casts timestamps to `TIMESTAMP_TZ`, derives `goal_category` (`Open Play` / `Penalty` / `Own Goal`), and converts kickoff times to Eastern timezone. Views materialized in Snowflake.

**MARTS** — analytics-ready fact and dimension tables. Tables materialized in Snowflake.

| Model                 | Description                                                              |
| --------------------- | ------------------------------------------------------------------------ |
| `fct_goals`           | Goal events joined to game context — scoring team, match date, day name  |
| `fct_games`           | Completed matches with derived result type, total goals, goal difference  |
| `dim_teams`           | Current standings snapshot per team including playoff position flag       |
| `mart_player_stats`   | Current season top scorers derived from match goal events                 |
| `mart_league_summary` | Aggregate per-competition metrics: matches, goals, home/away splits       |

dbt tests cover `not_null`, `unique`, `accepted_values`, and `relationships` across all models. Run the full suite:

```bash
cd scorestream_dbt
source dbt-env/bin/activate
dbt run
dbt test
dbt docs generate && dbt docs serve  # lineage graph at localhost:8080
```

---

## API Endpoints

```
GET   /                              — Service info
GET   /health                        — DB and cache connectivity
GET   /health/pipeline               — Pipeline component status
GET   /games                         — Games, filterable by ?status=, ?league=, ?window=
GET   /games/{game_id}               — Single game
GET   /games/{game_id}/stats         — Goal events for a game
GET   /standings                     — League/group table by ?league=
GET   /leagues                       — All competitions with data
POST  /chat                          — Natural language query (legacy)
WS    /ws                            — Real-time score/standings push
WS    /ws/chat                       — Streamed AI chat

GET   /analytics/top-scorers         — Top scorers from Snowflake mart, ?league=, ?limit=
GET   /analytics/league-summary      — Per-competition aggregate metrics from Snowflake
GET   /analytics/team/{id}/form      — Last N results for a team from Snowflake
GET   /analytics/goals/breakdown     — Goal type breakdown (open play / penalty / own goal)
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
│   └── espn_producer.py              # ESPN → Kafka (6 competitions)
├── spark/
│   ├── streaming_job.py              # Local PySpark consumer
│   └── streaming_job_aws.py          # AWS Glue streaming consumer
├── scheduler/
│   ├── Dockerfile
│   ├── entrypoint.sh                 # Routes SCHEDULER_JOB env var to script
│   ├── refresh_standings.py
│   ├── refresh_season_stats.py
│   └── archive_daily.py              # Nightly Parquet → S3 → Snowflake load
├── dags/
│   ├── standings_refresh.py
│   ├── season_stats_refresh.py
│   └── epl_daily_archive.py
├── api/
│   ├── main.py                       # FastAPI + WebSocket + /ws/chat
│   ├── snowflake_db.py               # Snowflake connection (Secrets Manager)
│   └── routers/
│       └── analytics.py              # /analytics/* endpoints → Snowflake marts
├── scorestream_dbt/                  # dbt project
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── staging/
│   │   │   ├── _sources.yml
│   │   │   ├── _staging.yml
│   │   │   ├── stg_scorestream__games.sql
│   │   │   ├── stg_scorestream__goals.sql
│   │   │   ├── stg_scorestream__standings.sql
│   │   │   └── stg_scorestream__season_stats.sql
│   │   └── marts/
│   │       ├── _marts.yml
│   │       ├── fct_goals.sql
│   │       ├── fct_games.sql
│   │       ├── dim_teams.sql
│   │       ├── mart_player_stats.sql
│   │       └── mart_league_summary.sql
│   ├── macros/
│   │   └── generate_schema_name.sql
│   └── seeds/
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
│           ├── MatchesTab.jsx
│           ├── PipelineTab.jsx
│           └── ChatTab.jsx
├── infra/                            # AWS CDK (Python)
│   ├── app.py
│   ├── network_stack.py
│   ├── rds_stack.py                  # Permanent — never destroyed
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

cdk deploy NetworkStack
cdk deploy RdsStack
cdk deploy DataStack
cdk deploy MskStack
cdk deploy ComputeStack
cdk deploy EdgeStack
cdk deploy MonitoringStack
```

### Secrets

After deploy, set secret values:

```bash
aws secretsmanager put-secret-value \
    --secret-id "scorestream/anthropic_api_key" \
    --secret-string "your-key"

aws secretsmanager put-secret-value \
    --secret-id "scorestream/football_data_api_key" \
    --secret-string "your-key"

aws secretsmanager put-secret-value \
    --secret-id "scorestream/snowflake-credentials" \
    --secret-string '{
        "account": "your-account",
        "user": "your-user",
        "password": "your-password",
        "warehouse": "SCORESTREAM_WH",
        "database": "SCORESTREAM",
        "schema": "RAW"
    }'
```

RDS credentials are generated and managed automatically by RDS.

### Snowflake Setup

1. Create a Snowflake account (free trial at snowflake.com, AWS us-east-1)
2. Create warehouse `SCORESTREAM_WH`, database `SCORESTREAM`, schemas `RAW` / `STAGING` / `MARTS`
3. Create an IAM role with S3 read access to the Glue bucket and configure a Snowflake storage integration
4. Update the IAM trust policy with Snowflake's `STORAGE_AWS_IAM_USER_ARN` and `STORAGE_AWS_EXTERNAL_ID`
5. Create the external stage pointing at the S3 archive folder
6. Run `dbt run` to build all models

The nightly archive task automatically triggers a Snowflake load after writing Parquet files to S3.

---

## Engineering Challenges

**Real-time clock interpolation** — ESPN updates its match clock roughly every 60 seconds. The match detail view interpolates between updates using `setInterval`, resetting on each confirmed server value, with separate state for the display clock and the progress bar to avoid the bar racing ahead of actual match time.

**Goal correction handling** — ESPN refines published goal data after the fact: changing goal type, reassigning scorer credit, or retracting goals via VAR. A unique constraint on `(game_id, team_id, seconds)` combined with delete-then-upsert in Spark handles all three cases. Penalty shootout kicks are filtered using ESPN's `shootout` flag with a defensive fallback on clock value (≥7200s in STATUS_FINAL_PEN games) since the flag is sometimes absent on late-corrected kicks.

**UTC-correct date grouping** — Late-evening kickoffs (9-10pm EDT) cross midnight UTC and land on the next calendar day. All date grouping uses Eastern Time via `toLocaleDateString('en-US', { timeZone: 'America/New_York' })`, and the backend window filter uses PostgreSQL's AT TIME ZONE conversion to anchor boundaries to Eastern midnight rather than UTC midnight.

**Multi-competition pipeline** — Extending from EPL to six competitions required generalizing every layer: LEAGUES dict in the producer, renamed Kafka topics (epl._ → sports._), league column throughout the schema, group_name/note/note_color/logo_url on standings.

**Streamed AI chat** — Moving from a blocking HTTP POST to a WebSocket-streamed response required structuring the pipeline so SQL generation, query execution, and chart detection run synchronously first, then the answer-formatting step streams token-by-token. Two separate WebSocket connections (useWebSocket for scores, useChatWebSocket for chat) use distinct environment variables to prevent the silent URL-collision bug where both hooks read the same env var and connect to the wrong endpoint.

**Text-to-SQL with derived-category awareness** — Several football questions map to derived values: "open play" is `own_goal = false AND penalty_goal = false`, zero goals is a COUNT of 0 not an empty result set. Schema documentation and example queries explicitly spell out these derivations so Claude doesn't report available data as missing.

**Operational vs analytical data separation** — PostgreSQL serves the real-time application layer: low-latency upserts, connection pooling, Redis pub/sub. Snowflake serves the analytical layer: columnar storage for aggregate queries, dbt-managed semantic models, mart tables that non-technical stakeholders can query directly. The nightly archive task is the bridge — it writes Parquet snapshots to S3, which Snowflake loads via an external stage, keeping the two layers decoupled with no direct database-to-database connection.

**dbt semantic modeling** — Staging models enforce data contracts (not_null, accepted_values, relationship tests) before data reaches marts. A custom `generate_schema_name` macro overrides dbt's default schema concatenation behavior so models land in `STAGING` and `MARTS` rather than `RAW_STAGING` and `RAW_MARTS`. Mart models use Snowflake's `QUALIFY ROW_NUMBER()` for window-function-safe top-N selection, avoiding the nested window function limitation that standard SQL approaches hit.

**AWS architecture decisions** — EventBridge-scheduled Fargate tasks replace MWAA (managed Airflow) as the batch layer — the three scheduled jobs run for seconds every 15-30 minutes, making MWAA's $354/month minimum unjustifiable. MSK with IAM authentication replaces local Kafka — no credential management beyond the task role. Glue streaming with S3 checkpoints replaces the local Spark container. RDS lives in its own permanent `RdsStack` with `RemovalPolicy.RETAIN` and deletion protection — separating it from DataStack eliminates the VPC subnet group conflict that occurs when DataStack is torn down and recreated, which previously stranded RDS in an orphaned network.

**Historical data backfill** — ESPN retains only ~3 weeks of scoreboard history. Football-data.org fills the gap for full-season data, but uses a completely different team ID numbering system. A manually curated mapping of 96+ teams cross-referenced by querying ESPN's live scoreboard across 30 days ensures historical games display correct logos regardless of which source populated them.

---

## What's Next

- Stream chat responses immediately on SQL completion rather than waiting for chart detection
- Extend `/analytics/*` endpoints with per-team and per-player drill-down views
- Add incremental dbt models to replace nightly full-refresh once data volume grows
- Production hardening: Multi-AZ RDS, MSK replication factor 3, WAF on ALB
- CI/CD pipeline: GitHub Actions building and pushing images on merge, CDK deploy on tag