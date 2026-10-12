from datetime import datetime, timedelta
import psycopg2
import pandas as pd
import os
import json
import boto3
import io
import snowflake.connector

def get_snowflake_credentials():
    if os.environ.get("SNOWFLAKE_ACCOUNT"):
        return {
            "user": os.environ.get("SNOWFLAKE_USER"),
            "password": os.environ.get("SNOWFLAKE_PASSWORD"),
            "account": os.environ.get("SNOWFLAKE_ACCOUNT"),
            "warehouse": os.environ.get("SNOWFLAKE_WAREHOUSE", "SCORESTREAM_WH"),
            "database": os.environ.get("SNOWFLAKE_DATABASE", "SCORESTREAM"),
            "schema": os.environ.get("SNOWFLAKE_SCHEMA", "MARTS")
        }

    client = boto3.client('secretsmanager', region_name='us-east-1')
    secret = client.get_secret_value(SecretId='scorestream/snowflake-credentials')
    return json.loads(secret['SecretString'])

def get_snowflake_connection():
    credentials = get_snowflake_credentials()
    conn = snowflake.connector.connect(
        user=credentials['user'],
        password=credentials['password'],
        account=credentials['account'],
        warehouse=credentials['warehouse'],
        database=credentials['database'],
        schema='MARTS'
    )
    return conn

def get_rds_credentials():
    client = boto3.client('secretsmanager', region_name='us-east-1')
    secret = client.get_secret_value(SecretId='scorestream/rds-credentials')
    return json.loads(secret['SecretString'])

def get_db(credentials):
    return psycopg2.connect(
        host=credentials['host'],
        database=credentials['dbname'],
        user=credentials['username'],
        password=credentials['password'],
        port=int(credentials['port'])
    )

def archive_games(conn, s3_client, bucket, date_str):
    df = pd.read_sql("SELECT * FROM games", conn)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    key = f"archive/games/{date_str}.parquet"
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())
    
    print(f"Archived {len(df)} games to s3://{bucket}/{key}")


def archive_goals(conn, s3_client, bucket, date_str):
    df = pd.read_sql("SELECT * FROM goals", conn)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    key = f"archive/goals/{date_str}.parquet"
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())

    print(f"Archived {len(df)} goals to s3://{bucket}/{key}")

def archive_standings(conn, s3_client, bucket, date_str):
    df = pd.read_sql("SELECT * FROM standings", conn)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    key = f"archive/standings/{date_str}.parquet"
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())

    print(f"Archived {len(df)} standings to s3://{bucket}/{key}")

def main():
    date_str = datetime.now().strftime("%Y-%m-%d")
    bucket = os.environ['ARCHIVE_BUCKET']

    print('[archive] Starting archive process for date:', date_str)

    credentials = get_rds_credentials()
    conn = get_db(credentials)
    s3_client = boto3.client('s3', region_name='us-east-1')

    try:
        archive_games(conn, s3_client, bucket, date_str)
        archive_goals(conn, s3_client, bucket, date_str)
        archive_standings(conn, s3_client, bucket, date_str)
        load_into_snowflake(date_str, bucket)
        print('[archive] Archive process completed successfully for date:', date_str)
    except Exception as e:
        print('[archive] Error during archive process for date:', date_str)
        print('[archive] Error details:', str(e))
        raise
    finally:
        conn.close()

def load_into_snowflake(date_str, bucket):
    conn = get_snowflake_connection()
    cursor = conn.cursor()

    try:
        for table in ['games', 'goals', 'standings']:
            key = f"archive/{table}/{date_str}.parquet"
            s3_path = f"s3://{bucket}/{key}"

            cursor.execute(f"""
                COPY INTO RAW.{table}_raw
                FROM '{s3_path}'
                STORAGE_INTEGRATION = scorestream_s3_integration
                FILE_FORMAT = (TYPE = PARQUET)
                MATCH_BY_COLUMN_NAME = CASE_INSENSITIVE
                PURGE = FALSE
            """)
            print(f"[snowflake] Loaded {table} successfully.")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()