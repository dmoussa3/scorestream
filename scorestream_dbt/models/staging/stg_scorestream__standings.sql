WITH source AS (
    SELECT * FROM {{ source('scorestream_raw', 'standings') }}
),

renamed AS (
    SELECT
        team_id,
        league,
        season,
        team_name,
        group_name,
        wins,
        losses,
        draws,
        points,
        goals_for,
        goals_against,
        goal_diff,
        matches_played,
        rank,
        deductions,
        note,
        note_color,
        logo_url,
        last_updated
    FROM source
    WHERE team_id IS NOT NULL
      AND league  IS NOT NULL
)

SELECT * FROM renamed