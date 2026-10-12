from fastapi import APIRouter, Query, HTTPException
from typing import Optional
from api.snowflake_db import get_snowflake_connection

router = APIRouter(prefix="/analytics", tags=["analytics"])

@router.get("/top-scorers")
def top_scorers(league: Optional[str] = Query(None, description="Filter by league"), limit: int = Query(10, ge=1, le=50)):
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()

        if league:
            cursor.execute(f"""
                SELECT player_name, team_name, league, goals, assists, penalties
                FROM SCORESTREAM.MARTS.MART_PLAYER_STATS
                WHERE league = %s
                ORDER BY goals DESC
                LIMIT %s
            """, (league, limit))
        else:
            cursor.execute(f"""
                SELECT player_name, team_name, league, goals, assists, penalties
                FROM SCORESTREAM.MARTS.MART_PLAYER_STATS
                ORDER BY goals DESC
                LIMIT %s
            """, (limit,))

        results = cursor.fetchall()
        cols = [desc[0].lower() for desc in cursor.description]
        conn.close()

        return [dict(zip(cols, row)) for row in results]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/league-summary")
def league_summary():
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT league, matches_played, total_goals, avg_goals_per_game, home_wins, away_wins, draws, top_scorer
            FROM SCORESTREAM.MARTS.MART_LEAGUE_SUMMARY
            ORDER BY total_goals DESC
        """)

        results = cursor.fetchall()
        cols = [desc[0].lower() for desc in cursor.description]
        conn.close()

        return [dict(zip(cols, row)) for row in results]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/team/{team_id}/form")
def team_form(team_id: str, limit: int = Query(5, ge=1, le=10)):
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()

        cursor.execute(f"""
            SELECT game_id, league, home_team_name, away_team_name, home_score, away_score, result, result_type, match_date, match_day
            FROM SCORESTREAM.MARTS.FCT_GAMES
            WHERE home_id = %s or away_id = %s
            ORDER BY match_date DESC
            LIMIT %s
        """, (team_id, team_id, limit))

        results = cursor.fetchall()
        cols = [desc[0].lower() for desc in cursor.description]
        conn.close()

        return [dict(zip(cols, row)) for row in results]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/goals/breakdown")
def goals_breakdown(league: Optional[str] = Query(None, description="Filter by league")):
    try:
        conn = get_snowflake_connection()
        cursor = conn.cursor()

        if league:
            cursor.execute(f"""
                SELECT goal_category, COUNT(*) as total, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
                FROM SCORESTREAM.MARTS.FCT_GOALS
                WHERE league = %s
                GROUP BY goal_category
                ORDER BY total DESC
            """, (league.lower(),))
        else:
            cursor.execute(f"""
                SELECT goal_category, COUNT(*) as total, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) as pct
                FROM SCORESTREAM.MARTS.FCT_GOALS
                GROUP BY goal_category
                ORDER BY total DESC
            """)

        results = cursor.fetchall()
        cols = [desc[0].lower() for desc in cursor.description]
        conn.close()

        return [dict(zip(cols, row)) for row in results]
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))