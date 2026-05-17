from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
import psycopg2

DATABASE_URL = "postgresql://admin:password@postgres:5432/scorestream"
ESPN_BASE = "https://site.api.espn.com/apis/v2/sports/soccer"

LEAGUES = {
    'epl': 'eng.1',
    'laliga': 'esp.1',
    'bundesliga': 'ger.1',
    'seriea': 'ita.1',
    'ligue1': 'fra.1'
}

def fetch_standings(league_name: str, league_id: str):
    url = f"{ESPN_BASE}/{league_id}/standings"

    try:
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        
        # Process data and push to XCom for the next task
        standings = []

        for group in resp.json().get('children', []):
            for entry in group.get('standings', {}).get('entries', []):
                standings.append(entry)
        return standings
    except requests.RequestException as e:
        print(f"[airflow] Error fetching standings for {league_name}: {e}")
        return []

def parse_standings(entry: dict, league_name: str):
    try:
        stats = {s['name']: s['value'] for s in entry.get('stats', []) if 'value' in s}
        team = entry['team']

        return {
            'team_id': team['id'],
            'league': league_name,
            'team_name': team['displayName'],
            'wins': int(stats.get('wins', 0)),
            'losses': int(stats.get('losses', 0)),
            'draws': int(stats.get('ties', 0)),
            'points': int(stats.get('points', 0)),
            'goals_for': int(stats.get('pointsFor', 0)),
            'goals_against': int(stats.get('pointsAgainst', 0)),
            'goal_diff': int(stats.get('pointDifferential', 0)),
            'matches_played': int(stats.get('gamesPlayed', 0)),
            "rank": int(stats.get("rank", 0)),
            'deductions': int(stats.get('deductions', 0))
        }
    except (KeyError, ValueError) as e:
        print(f"Error parsing standings entry: {e}")
        return None
    
def refresh_all_standings(**context):
    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()
    total = 0

    try:
        for league_key, sport_path in LEAGUES.items():
            entries = fetch_standings(league_key, sport_path)
            if not entries:
                print(f"[airflow] No standings data for {league_key} — skipping")
                continue

            records = [parse_standings(e, league_key) for e in entries]
            records = [r for r in records if r is not None]

            for record in records:
                cursor.execute("""
                    INSERT INTO standings (
                        team_id, league, team_name, wins, draws, losses,
                        points, goals_for, goals_against, goal_diff,
                        matches_played, rank, last_updated
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (team_id, league) DO UPDATE SET
                        wins           = EXCLUDED.wins,
                        draws          = EXCLUDED.draws,
                        losses         = EXCLUDED.losses,
                        points         = EXCLUDED.points,
                        goals_for      = EXCLUDED.goals_for,
                        goals_against  = EXCLUDED.goals_against,
                        goal_diff      = EXCLUDED.goal_diff,
                        matches_played = EXCLUDED.matches_played,
                        rank           = EXCLUDED.rank,
                        last_updated   = NOW()
                """, (
                    record["team_id"],
                    record["league"],
                    record["team_name"],
                    record["wins"],
                    record["draws"],
                    record["losses"],
                    record["points"],
                    record["goals_for"],
                    record["goals_against"],
                    record["goal_diff"],
                    record["matches_played"],
                    record["rank"]
                ))
            
            total += len(records)
            print(f"[airflow] {league_key}: upserted {len(records)} teams")

        conn.commit()
        print(f"[airflow] Standings refresh complete — {total} total records")
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        cursor.close()
        conn.close()

with DAG(
    dag_id='standings_refresh',
    start_date=datetime(2026, 1, 1),
    schedule_interval="*/30 * * * *",
    catchup=False,
    is_paused_upon_creation=False,
    default_args={
        'retries': 2,
        'retry_delay': timedelta(minutes=5)
    }
) as dag:

    refresh_task = PythonOperator(
        task_id='refresh_standings',
        python_callable=refresh_all_standings,
        provide_context=True
    )

    refresh_task