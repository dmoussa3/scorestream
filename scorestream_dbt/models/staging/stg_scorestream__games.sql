WITH source AS (
    SELECT * FROM {{ source('scorestream_raw', 'games') }}
),

renamed AS (
    SELECT
        game_id,
        league,
        home_team,
        home_team_name,
        home_id,
        home_logo,
        away_team,
        away_team_name,
        away_id,
        away_logo,
        COALESCE(home_score, 0)     AS home_score,
        COALESCE(away_score, 0)     AS away_score,
        shootout_home,
        shootout_away,
        round,
        period,
        clock,
        status,
        status_detail,
        CONVERT_TIMEZONE('America/New_York', start_time)
                                    AS start_time_eastern,
        start_time                  AS start_time_utc,
        matchday,
        last_updated
    FROM source
    WHERE game_id IS NOT NULL
      AND league  IS NOT NULL
)

SELECT * FROM renamed