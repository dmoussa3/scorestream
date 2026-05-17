from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta
import psycopg2
import pandas as pd

DATABASE_URL = "postgresql://admin:password@postgres:5432/scorestream"

def archive_games(**context):
    date_str = context['ds']
    conn = psycopg2.connect(DATABASE_URL)

    df = pd.read_sql("SELECT * FROM games", conn)
    df_standings = pd.read_sql("SELECT * FROM standings", conn)
    conn.close()

    games_output_path = f"/opt/airflow/archive/games/{date_str}.parquet"
    standings_output_path = f"/opt/airflow/archive/standings/{date_str}.parquet"
    
    df.to_parquet(games_output_path, index=False)
    df_standings.to_parquet(standings_output_path, index=False)
    
    print(f"Archived {len(df)} games for {date_str} to {games_output_path}")
    print(f"Archived {len(df_standings)} standings for {date_str} to {standings_output_path}")


def archive_goals(**context):
    date_str = context['ds']
    conn = psycopg2.connect(DATABASE_URL)

    df = pd.read_sql("SELECT * FROM goals", conn)
    conn.close()

    output_path = f"/opt/airflow/archive/goals/{date_str}.parquet"
    df.to_parquet(output_path, index=False)
    print(f"Archived {len(df)} goals for {date_str} to {output_path}")

with DAG(
    dag_id='epl_daily_archive',
    start_date=datetime(2026, 1, 1),
    schedule_interval="0 0 * * *",
    catchup=False,
    is_paused_upon_creation=False,
    default_args={
        'retries': 5,
        'retry_delay': timedelta(minutes=5)
    }
) as dag:
    
    archive_games_task = PythonOperator(
        task_id='archive_games',
        python_callable=archive_games,
        provide_context=True
    )

    archive_goals_task = PythonOperator(
        task_id='archive_goals',
        python_callable=archive_goals,
        provide_context=True
    )

    [archive_games_task, archive_goals_task]