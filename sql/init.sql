-- ScoreStream Database Schema
-- Runs automatically when the postgres container first starts

-- ── Games ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS games (
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
    status          VARCHAR NOT NULL,  -- STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_FINAL
    status_detail   VARCHAR,
    start_time      TIMESTAMP,
    last_updated    TIMESTAMP DEFAULT NOW()
);

-- ── Goals ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goals (
    id              SERIAL PRIMARY KEY,
    game_id         VARCHAR REFERENCES games(game_id) ON DELETE CASCADE,
    player_id       VARCHAR NOT NULL,
    player_name     VARCHAR NOT NULL,
    team_id         VARCHAR NOT NULL,
    minute          VARCHAR,
    seconds         INT,
    goal_type       VARCHAR,  -- e.g., "Volley", "Penalty", "Own Goal"
    own_goal        BOOLEAN DEFAULT FALSE,
    penalty_goal    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),

    UNIQUE(game_id, player_id, minute, goal_type)
);

-- ── Standings ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS standings (
    team_id         VARCHAR PRIMARY KEY,
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
    last_updated    TIMESTAMP DEFAULT NOW()
);

-- ── Metadata ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pipeline_metadata (
    key             VARCHAR PRIMARY KEY,
    value           TEXT,
    last_updated    TIMESTAMP DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_goals_game ON goals(game_id);
CREATE INDEX IF NOT EXISTS idx_games_status       ON games(status);

-- ── Seed message ────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE 'ScoreStream schema initialized successfully.';
END $$;
