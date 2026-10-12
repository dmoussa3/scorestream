import snowflake.connector
import boto3
import json
import os
from functools import lru_cache

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