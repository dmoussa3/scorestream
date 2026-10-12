WITH source AS (
    SELECT * FROM {{ source('scorestream_raw', 'goals') }}
),

renamed AS (
    SELECT
        id,
        game_id,
        league,
        player_id,
        player_name,
        team_id,
        minute,
        seconds,
        goal_type,
        own_goal,
        penalty_goal,
        CASE
            WHEN own_goal      THEN 'Own Goal'
            WHEN penalty_goal  THEN 'Penalty'
            ELSE 'Open Play'
        END                         AS goal_category,
        created_at
    FROM source
    WHERE game_id IS NOT NULL
)

SELECT * FROM renamed