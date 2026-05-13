from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import requests
import psycopg2

DATABASE_URL = "postgresql://admin:password@postgres:5432/scorestream"

def fetch_standings(**context):
    url = "https://site.api.espn.com/apis/v2/sports/soccer/eng.1/standings"
    resp = requests.get(url, timeout=10)
    data = resp.json()
    
    # Process data and push to XCom for the next task
    standings = []

    for group in data.get('children', []):
        for entry in group.get('standings', {}).get('entries', []):
            standings.append(entry)

    context['ti'].xcom_push(key='standings', value=standings)
    print(f"Fetched {len(standings)} standings entries.")

def load_standings(**context):
    standings = context['ti'].xcom_pull(key='standings', task_ids='fetch_standings')    

    conn = psycopg2.connect(DATABASE_URL)
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM standings")

        for entry in standings:
            stats = {s['name']: s['value'] for s in entry.get('stats', []) if 'value' in s}
            team = entry['team']

            cursor.execute("""
                INSERT INTO standings (team_id, team_name, wins, losses, draws, points, goals_for, goals_against, goal_diff, matches_played, rank, deductions, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            """, (
                team['id'],
                team['displayName'],
                int(stats.get('wins', 0)),
                int(stats.get('losses', 0)),
                int(stats.get('ties', 0)),
                int(stats.get('points', 0)),
                int(stats.get('pointsFor', 0)),
                int(stats.get('pointsAgainst', 0)),
                int(stats.get('pointDifferential', 0)),
                int(stats.get('gamesPlayed', 0)),
                int(stats.get('rank', 0)),
                int(stats.get('deductions', 0))
            ))

        conn.commit()
        print(f"Loaded {len(standings)} standings entries into the database.")
    except Exception as e:
        print(f"Error occurred while loading standings: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()

with DAG(
    dag_id='epl_standings_refresh',
    start_date=datetime(2026, 1, 1),
    schedule_interval="*/30 * * * *",
    catchup=False,
    is_paused_upon_creation=False,
    default_args={
        'retries': 2,
        'retry_delay': timedelta(minutes=5)
    }
) as dag:
    
    fetch_task = PythonOperator(
        task_id='fetch_standings',
        python_callable=fetch_standings,
        provide_context=True
    )

    load_task = PythonOperator(
        task_id='load_standings',
        python_callable=load_standings,
        provide_context=True
    )

    fetch_task >> load_task