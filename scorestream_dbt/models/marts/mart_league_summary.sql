WITH games AS (
    SELECT * FROM {{ ref('fct_games') }}
),

goals AS (
    SELECT * FROM {{ ref('fct_goals') }}
),

game_summary AS (
    SELECT
        league,
        COUNT(*)                                        AS matches_played,
        SUM(total_goals)                                AS total_goals,
        ROUND(AVG(total_goals), 2)                      AS avg_goals_per_game,
        SUM(CASE WHEN result_type = 'home_win' THEN 1 ELSE 0 END)
                                                        AS home_wins,
        SUM(CASE WHEN result_type = 'away_win' THEN 1 ELSE 0 END)
                                                        AS away_wins,
        SUM(CASE WHEN result_type = 'draw'     THEN 1 ELSE 0 END)
                                                        AS draws
    FROM games
    GROUP BY league
),

player_goal_counts AS (
    SELECT
        league,
        player_name,
        COUNT(*)                                        AS goals
    FROM goals
    WHERE own_goal = FALSE
    GROUP BY league, player_name
),

top_scorers AS (
    SELECT
        league,
        player_name                                     AS top_scorer
    FROM player_goal_counts
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY league
        ORDER BY goals DESC
    ) = 1
),

combined AS (
    SELECT
        gs.league,
        gs.matches_played,
        gs.total_goals,
        gs.avg_goals_per_game,
        gs.home_wins,
        gs.away_wins,
        gs.draws,
        ts.top_scorer
    FROM game_summary gs
    LEFT JOIN top_scorers ts ON gs.league = ts.league
)

SELECT * FROM combined
ORDER BY total_goals DESC