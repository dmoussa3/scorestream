import json
import os
import traceback
import boto3
import psycopg2
import psycopg2.pool
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, size
from pyspark.sql.types import (
    StructType, StringType, IntegerType,
    BooleanType, ArrayType
)
from awsglue.context import GlueContext
from awsglue.job import Job
from awsglue.utils import getResolvedOptions
from datetime import timezone, datetime
import time
import redis
import sys
import socket

args = getResolvedOptions(sys.argv, [
    'JOB_NAME',
    'KAFKA_BOOTSTRAP_SERVERS',
    'CHECKPOINT_BUCKET',
    'AWS_REGION',
    'REDIS_HOST',
    'REDIS_PORT',
    'RDS_SECRET_NAME',
])

RDS_SECRET_NAME = args['RDS_SECRET_NAME']
REDIS_HOST = args['REDIS_HOST']
REDIS_PORT = int(args.get('REDIS_PORT', 6379))

KAFKA_SERVERS = args['KAFKA_BOOTSTRAP_SERVERS']
CHECKPOINT_BUCKET = args['CHECKPOINT_BUCKET']
CHECKPOINT_BASE = f"s3://{CHECKPOINT_BUCKET}/checkpoints"
AWS_REGION = args.get('AWS_REGION', 'us-east-1')

spark = SparkSession.builder \
    .appName('ScoreStreamGlue') \
    .config('spark.sql.shuffle.partitions', '2') \
    .getOrCreate()

glue_context = GlueContext(spark.sparkContext)
job = Job(glue_context)
job.init(args['JOB_NAME'], args)

raw_stream = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_SERVERS) \
    .option("kafka.security.protocol", "SASL_SSL") \
    .option("kafka.sasl.mechanism", "AWS_MSK_IAM") \
    .option("kafka.sasl.jaas.config", "software.amazon.msk.auth.iam.IAMLoginModule required;") \
    .option("kafka.sasl.client.callback.handler.class", "software.amazon.msk.auth.iam.IAMClientCallbackHandler") \
    .option("subscribe", "sports.live.scores") \
    .option("startingOffsets", "earliest") \
    .option("failOnDataLoss", "false") \
    .load() \
    .select(col("value").cast("string").alias("value"))

goal_schema = ArrayType(StructType()
    .add("player_id", StringType())
    .add("player_name", StringType())
    .add("team_id", StringType())
    .add("minute", StringType())
    .add("seconds", IntegerType())
    .add("goal_type", StringType())
    .add("own_goal", BooleanType())
    .add("penalty_goal", BooleanType())
    .add("league", StringType())
)

games_schema = StructType() \
    .add("game_id", StringType()) \
    .add("league", StringType()) \
    .add("home_team", StringType()) \
    .add("away_team", StringType()) \
    .add("home_team_name", StringType()) \
    .add("away_team_name", StringType()) \
    .add("home_id", StringType()) \
    .add("away_id", StringType()) \
    .add("status", StringType()) \
    .add("status_detail", StringType()) \
    .add("home_score", IntegerType()) \
    .add("away_score", IntegerType()) \
    .add("shootout_home", IntegerType()) \
    .add("shootout_away", IntegerType()) \
    .add("round", StringType()) \
    .add("period", IntegerType()) \
    .add("clock", StringType()) \
    .add("goals", goal_schema) \
    .add("start_time", StringType()) \
    .add("timestamp", StringType())    

df_scores = raw_stream.select(from_json(col("value"), games_schema).alias("data")).select("data.*")

# _pool = None

# def get_pool():
#     global _pool
#     if _pool is None:
#         _pool = psycopg2.pool.SimpleConnectionPool(
#             minconn= 1, 
#             maxconn= 10,  # min and max connections
#             host=DB_HOST,
#             port=DB_PORT,
#             dbname=DB_NAME,
#             user=DB_USER,
#             password=DB_PASS
#         )
#     return _pool

def process_games(df_batch, batch_id):
    """Write a batch of game updates to the database."""
    if df_batch.isEmpty():
        return
    
    import boto3, json, redis as redis_lib 
    import psycopg2
    from datetime import datetime, timezone

    client = boto3.client('secretsmanager', region_name=AWS_REGION)
    secret = client.get_secret_value(SecretId=RDS_SECRET_NAME)
    c = json.loads(secret['SecretString'])

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    conn = None
    cursor = None
    try:
        conn = psycopg2.connect(
            host=c['host'],
            port=int(c['port']),
            dbname=c['dbname'],
            user=c['username'],
            password=c['password'],
            connect_timeout=30,
            sslmode='require'
        )
        cursor = conn.cursor()
        rows = df_batch.collect()

        for row in rows:
            cursor.execute("""
                INSERT INTO games (game_id, league, home_team, home_team_name, home_id, away_team, away_team_name, away_id, home_score, away_score, shootout_home, shootout_away, round, period, clock, status, status_detail, start_time, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (game_id) DO UPDATE SET
                    league = EXCLUDED.league,
                    home_team = EXCLUDED.home_team,
                    home_team_name = EXCLUDED.home_team_name,
                    home_id = EXCLUDED.home_id,
                    away_team = EXCLUDED.away_team,
                    away_team_name = EXCLUDED.away_team_name,
                    away_id = EXCLUDED.away_id,
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score,
                    shootout_home = EXCLUDED.shootout_home,
                    shootout_away = EXCLUDED.shootout_away,
                    status = EXCLUDED.status,
                    status_detail = EXCLUDED.status_detail,
                    round = EXCLUDED.round,
                    period = EXCLUDED.period,
                    clock = EXCLUDED.clock,
                    last_updated = NOW()
            """, (
                row.game_id,
                row.league,
                row.home_team,
                row.home_team_name,
                row.home_id,
                row.away_team,
                row.away_team_name,
                row.away_id,
                row.home_score,
                row.away_score,
                row.shootout_home,
                row.shootout_away,
                row.round,
                row.period,
                row.clock,
                row.status,
                row.status_detail,
                row.start_time
            ))
        conn.commit()
        print(f"[spark-games] Batch {batch_id} - Processed {len(rows)} records")

        try:
            r.publish("scorestream.updates", json.dumps({
                "type":      "games",
                "batch_id":  batch_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception as redis_e:
            print(f"[spark-games] Redis publish failed (non-fatal): {redis_e}")

    except Exception as e:
        import traceback
        print(f"[spark-games] Games batch {batch_id} ERROR type: {type(e).__name__}")
        print(f"[spark-games] Games batch {batch_id} ERROR: {e}")
        print(f"[spark-games] Traceback: {traceback.format_exc()}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

def process_goals(df_batch, batch_id):
    """Write a batch of goal events to the database."""    
    
    if df_batch.isEmpty():
        print(f"[spark-goals] Goals batch {batch_id} is empty, no games — skipping")
        return

    games_w_goals = df_batch \
        .filter(col("goals").isNotNull()) \
        .filter(size(col("goals")) > 0)

    if games_w_goals.isEmpty():
        print(f"[spark-goals] No games with goals in batch {batch_id}")
        return
    
    import boto3, json, redis as redis_lib   # ← local imports
    import psycopg2
    import socket
    from datetime import datetime, timezone

    client = boto3.client('secretsmanager', region_name=AWS_REGION)
    secret = client.get_secret_value(SecretId=RDS_SECRET_NAME)
    c = json.loads(secret['SecretString'])

    r = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)

    conn = None
    cursor = None

    try:
        conn = psycopg2.connect(
            host=c['host'],
            port=int(c['port']),
            dbname=c['dbname'],
            user=c['username'],
            password=c['password'],
            connect_timeout=30,
            sslmode='require'
        )
        cursor = conn.cursor()
        rows = games_w_goals.collect()

        for row in rows:
            game_id = row.game_id
            current_keys = [(g.team_id, g.seconds) for g in row.goals if g.seconds is not None]

            if current_keys:
                cursor.execute("""
                    DELETE FROM goals
                    WHERE game_id = %s AND (team_id, seconds) NOT IN %s
                """, ( game_id, tuple(current_keys) ))
            else:
                cursor.execute("""
                    DELETE FROM goals
                    WHERE game_id = %s
                """, (game_id,))

            for goal in row.goals:
                cursor.execute("""
                    INSERT INTO goals (game_id, league, player_id, player_name, team_id, minute, seconds, goal_type, own_goal, penalty_goal)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (game_id, team_id, seconds) DO UPDATE SET
                        player_id    = EXCLUDED.player_id,
                        player_name  = EXCLUDED.player_name,
                        goal_type    = EXCLUDED.goal_type,
                        minute       = EXCLUDED.minute,
                        own_goal     = EXCLUDED.own_goal,
                        penalty_goal = EXCLUDED.penalty_goal,
                        league       = EXCLUDED.league
                """, (
                    row.game_id,
                    goal.league,
                    goal.player_id,
                    goal.player_name or "Unknown",
                    goal.team_id,
                    goal.minute,
                    goal.seconds,
                    goal.goal_type,
                    goal.own_goal,
                    goal.penalty_goal
                ))

        conn.commit()

        try:
            r.publish("scorestream.updates", json.dumps({
                "type":      "games",
                "batch_id":  batch_id,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }))
        except Exception as redis_e:
            print(f"[spark-games] Redis publish failed (non-fatal): {redis_e}")

        print(f"[spark-goals] Batch {batch_id} - Processed {len(rows)} goal records")
    except Exception as e:
        print(f"[spark-goals] Batch {batch_id} - Error processing goals batch: {e}")
        if conn:
            conn.rollback()
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

games_query = df_scores.writeStream \
    .foreachBatch(process_games) \
    .outputMode("update") \
    .option("checkpointLocation", f"{CHECKPOINT_BASE}/games") \
    .trigger(processingTime="5 seconds") \
    .start()

time.sleep(5)

goals_query = df_scores.writeStream \
    .foreachBatch(process_goals) \
    .outputMode("update") \
    .option("checkpointLocation", f"{CHECKPOINT_BASE}/goals") \
    .trigger(processingTime="5 seconds") \
    .start()

spark.streams.awaitAnyTermination()
job.commit()