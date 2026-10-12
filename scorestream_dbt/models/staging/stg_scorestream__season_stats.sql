WITH source AS (
    SELECT * FROM {{ source('scorestream_raw', 'season_stats') }}
),

renamed AS (
    SELECT
        player_id,
        player_name,
        team_id,
        team_name,
        league,
        season,
        goals,
        assists,
        penalties,
        last_updated
    FROM source
    WHERE player_id IS NOT NULL
      AND league    IS NOT NULL
)

SELECT * FROM renamed