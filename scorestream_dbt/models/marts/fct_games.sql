WITH games AS (
    SELECT * FROM {{ ref('stg_scorestream__games') }}
),

enriched AS (
    SELECT
        game_id,
        league,
        home_team_name,
        away_team_name,
        home_id,
        away_id,
        home_score,
        away_score,
        COALESCE(shootout_home, 0)                      AS shootout_home,
        COALESCE(shootout_away, 0)                      AS shootout_away,
        home_score + away_score                         AS total_goals,
        ABS(home_score - away_score)                    AS goal_difference,
        CASE
            WHEN home_score > away_score  THEN home_team_name
            WHEN away_score > home_score  THEN away_team_name
            ELSE 'Draw'
        END                                             AS result,
        CASE
            WHEN home_score > away_score  THEN 'home_win'
            WHEN away_score > home_score  THEN 'away_win'
            ELSE 'draw'
        END                                             AS result_type,
        status,
        status_detail,
        round,
        matchday,
        period,
        clock,
        start_time_eastern::DATE                        AS match_date,
        DAYNAME(start_time_eastern)                     AS match_day,
        DATE_PART('hour', start_time_eastern)           AS kickoff_hour_eastern,
        start_time_utc,
        start_time_eastern,
        last_updated
    FROM games
    WHERE status IN ('STATUS_FULL_TIME', 'STATUS_FINAL')
)

SELECT * FROM enriched