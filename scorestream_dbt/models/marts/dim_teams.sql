WITH standings AS (
    SELECT * FROM {{ ref('stg_scorestream__standings') }}
),

teams AS (
    SELECT
        team_id,
        team_name,
        league,
        season,
        group_name,
        rank,
        points,
        wins,
        draws,
        losses,
        matches_played,
        goals_for,
        goals_against,
        goal_diff,
        deductions,
        note,
        note_color,
        logo_url,
        CASE
            WHEN league = 'mls' AND rank <= 9  THEN TRUE
            ELSE FALSE
        END                                             AS playoff_position,
        last_updated
    FROM standings
)

SELECT * FROM teams