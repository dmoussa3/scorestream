from datetime import datetime, timedelta
import psycopg2
import pandas as pd
import os
import json
import boto3
import psycopg2
import io

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


def archive_goals(conn, date_str, s3_client, bucket):
    df = pd.read_sql("SELECT * FROM goals", conn)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    key = f"archive/goals/{date_str}.parquet"
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())

    print(f"Archived {len(df)} goals to s3://{bucket}/{key}")

def archive_standings(conn, date_str, s3_client, bucket):
    df = pd.read_sql("SELECT * FROM standings", conn)

    buffer = io.BytesIO()
    df.to_parquet(buffer, index=False)
    buffer.seek(0)

    key = f"archive/standings/{date_str}.parquet"
    s3_client.put_object(Bucket=bucket, Key=key, Body=buffer.getvalue())

    print(f"Archived {len(df)} standings to s3://{bucket}/{key}")

def main():
    date_str = datetime.now().isoformat()
    bucket = os.environ['ARCHIVE_BUCKET']

    print('[archive] Starting archive process for date:', date_str)

    credentials = get_rds_credentials()
    conn = get_db(credentials)
    s3_client = boto3.client('s3', region_name='us-east-1')

    try:
        archive_games(conn, s3_client, bucket, date_str)
        archive_goals(conn, date_str, s3_client, bucket)
        archive_standings(conn, date_str, s3_client, bucket)
        print('[archive] Archive process completed successfully for date:', date_str)
    except Exception as e:
        print('[archive] Error during archive process for date:', date_str)
        print('[archive] Error details:', str(e))
        raise
    finally:
        conn.close()

if __name__ == "__main__":
    main()