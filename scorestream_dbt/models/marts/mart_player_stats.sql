WITH goals AS (
    SELECT
        player_id,
        player_name,
        team_id,
        scoring_team                AS team_name,
        league,
        COUNT(*)                    AS goals
    FROM {{ ref('fct_goals') }}
    WHERE own_goal = FALSE
    GROUP BY player_id, player_name, team_id, scoring_team, league
),

season_stats AS (
    SELECT * FROM {{ ref('stg_scorestream__season_stats') }}
),

combined AS (
    SELECT
        g.player_id,
        g.player_name,
        g.team_id,
        g.team_name,
        g.league,
        COALESCE(ss.season, 2026)           AS season,
        g.goals,
        COALESCE(ss.assists, 0)             AS assists,
        COALESCE(ss.penalties, 0)           AS penalties,
        g.goals + COALESCE(ss.assists, 0)   AS goal_contributions,
        COALESCE(ss.last_updated, CURRENT_TIMESTAMP())
                                            AS last_updated
    FROM goals g
    LEFT JOIN season_stats ss
        ON  g.player_id = ss.player_id
        AND g.league    = ss.league
)

SELECT * FROM combined
ORDER BY goals DESC