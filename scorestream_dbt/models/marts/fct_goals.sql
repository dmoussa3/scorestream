WITH goals AS (
    SELECT * FROM {{ ref('stg_scorestream__goals') }}
),

games AS (
    SELECT * FROM {{ ref('stg_scorestream__games') }}
),

joined AS (
    SELECT
        g.id                                            AS goal_id,
        g.game_id,
        gm.league,
        gm.home_team_name,
        gm.away_team_name,
        gm.start_time_eastern::DATE                     AS match_date,
        DAYNAME(gm.start_time_eastern)                  AS match_day,
        gm.home_score,
        gm.away_score,
        g.player_id,
        g.player_name,
        g.team_id,
        g.minute,
        g.seconds,
        g.goal_type,
        g.own_goal,
        g.penalty_goal,
        g.goal_category,
        CASE
            WHEN g.team_id = gm.home_id THEN gm.home_team_name
            WHEN g.team_id = gm.away_id THEN gm.away_team_name
        END                                             AS scoring_team
    FROM goals g
    JOIN games gm ON g.game_id = gm.game_id
)

SELECT * FROM joined