-- ScoreStream Database Schema
-- Runs automatically when the postgres container first starts

-- ── Games ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS games (
    league          VARCHAR DEFAULT 'epl',
    game_id         VARCHAR PRIMARY KEY,
    home_team       VARCHAR NOT NULL,
    home_team_name  VARCHAR NOT NULL,
    home_id         VARCHAR NOT NULL,
    home_logo       VARCHAR,
    away_team       VARCHAR NOT NULL,
    away_team_name  VARCHAR NOT NULL,
    away_id         VARCHAR NOT NULL,
    away_logo       VARCHAR,
    home_score      INT DEFAULT 0,
    away_score      INT DEFAULT 0,
    period          VARCHAR,
    clock           VARCHAR,
    status          VARCHAR NOT NULL,  -- STATUS_SCHEDULED, STATUS_IN_PROGRESS, STATUS_FINAL, etc.
    status_detail   VARCHAR,
    start_time      TIMESTAMP WITH TIME ZONE,
    matchday        INTEGER,
    last_updated    TIMESTAMP DEFAULT NOW()
);

-- ── Goals ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS goals (
    id              SERIAL PRIMARY KEY,
    game_id         VARCHAR REFERENCES games(game_id) ON DELETE CASCADE,
    league          VARCHAR DEFAULT 'epl',
    player_id       VARCHAR NOT NULL,
    player_name     VARCHAR NOT NULL,
    team_id         VARCHAR NOT NULL,
    minute          VARCHAR,
    seconds         FLOAT,
    goal_type       VARCHAR,  -- e.g., "Goal", "Goal - Header", "Penalty - Scored"
    own_goal        BOOLEAN DEFAULT FALSE,
    penalty_goal    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMP DEFAULT NOW(),

    -- Unique on (game_id, team_id, seconds) rather than player_id —
    -- ESPN sometimes reassigns which player scored at a fixed moment
    -- (e.g. correcting an own-goal credit), and the team+timing is the
    -- stable identity of the event, not the player attribution.
    UNIQUE(game_id, team_id, seconds)
);

-- ── Season Stats ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS season_stats (
    player_id     VARCHAR,
    player_name   VARCHAR,
    team_id       VARCHAR,
    team_name     VARCHAR,
    league        VARCHAR,
    season        INTEGER,
    goals         INTEGER DEFAULT 0,
    assists       INTEGER DEFAULT 0,
    penalties     INTEGER DEFAULT 0,
    last_updated  TIMESTAMP DEFAULT NOW(),
    PRIMARY KEY (player_id, league, season)
);

-- ── Standings ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS standings (
    team_id         VARCHAR NOT NULL,
    league          VARCHAR NOT NULL DEFAULT 'epl',
    season          INTEGER DEFAULT 2026,
    team_name       VARCHAR NOT NULL,
    group_name      VARCHAR,        -- World Cup group stage (e.g. 'Group A'); NULL for club leagues
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
    note            VARCHAR,        -- e.g. "Advance to Round of 32" (World Cup qualification status)
    note_color      VARCHAR,        -- hex color associated with the note, from ESPN
    logo_url        VARCHAR,        -- direct ESPN CDN logo URL for the team
    last_updated    TIMESTAMP DEFAULT NOW(),

    PRIMARY KEY (team_id, league, season)
);

-- ── Metadata ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pipeline_metadata (
    key             VARCHAR PRIMARY KEY,
    value           TEXT,
    last_updated    TIMESTAMP DEFAULT NOW()
);

-- ── Indexes ─────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_goals_game        ON goals(game_id);
CREATE INDEX IF NOT EXISTS idx_goals_league      ON goals(league);
CREATE INDEX IF NOT EXISTS idx_goals_seconds     ON goals(game_id, seconds ASC);
CREATE INDEX IF NOT EXISTS idx_games_status      ON games(status);
CREATE INDEX IF NOT EXISTS idx_games_league      ON games(league);
CREATE INDEX IF NOT EXISTS idx_games_last_update ON games(last_updated DESC);
CREATE INDEX IF NOT EXISTS idx_standings_league  ON standings(league, season);

-- ── Seed message ────────────────────────────────────────────────────
DO $$
BEGIN
    RAISE NOTICE 'ScoreStream schema initialized successfully.';
END $$;