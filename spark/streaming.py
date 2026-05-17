import json
import os
import traceback
from pyspark.sql.functions import size
import psycopg2
import psycopg2.pool
from pyspark.sql import SparkSession
from pyspark.sql.functions import from_json, col, explode
from pyspark.sql.types import (
    StructType, StringType, IntegerType,
    BooleanType, ArrayType
)
from datetime import timezone, datetime
import time
import redis

KAFKA_SERVERS = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "kafka:29092")
DATABASE_URL  = os.getenv("DATABASE_URL", "postgresql://admin:password@postgres:5432/scorestream")

spark = SparkSession.builder \
    .appName("ScoreStream") \
    .master("local[*]") \
    .config("spark.sql.shuffle.partitions", "2") \
    .config("spark.jars.packages", 
            "org.apache.spark:spark-sql-kafka-0-10_2.12:3.4.0,"
            "org.postgresql:postgresql:42.6.0") \
    .config("spark.sql.shuffle.partitions", "2") \
    .config("spark.default.parallelism", "2") \
    .config("spark.streaming.backpressure.enabled", "true") \
    .config("spark.sql.streaming.forceDeleteTempCheckpointLocation", "true") \
    .getOrCreate()

spark.sparkContext.setLogLevel("WARN")
print("[spark] SparkSession started")
time.sleep(30)

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
    .add("period", IntegerType()) \
    .add("clock", StringType()) \
    .add("goals", goal_schema) \
    .add("start_time", StringType()) \
    .add("timestamp", StringType())

raw_stream = spark.readStream \
    .format("kafka") \
    .option("kafka.bootstrap.servers", KAFKA_SERVERS) \
    .option("subscribe", "sports.live.scores") \
    .option("startingOffsets", "earliest") \
    .option("failOnDataLoss", "false") \
    .load() \
    .select(col("value").cast("string").alias("value"))

scores_stream = raw_stream.select(col("value").cast("string").alias("value"))
df_scores = scores_stream.select(from_json(col("value"), games_schema).alias("data")).select("data.*")

cache = redis.Redis(host=os.getenv("REDIS_HOST", "redis"), port=6379, decode_responses=True)

_pool = None

def get_pool():
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.SimpleConnectionPool(
            minconn= 1, 
            maxconn= 10,  # min and max connections
            dsn=os.getenv("DATABASE_URL")
        )
    return _pool


def process_games(df_batch, batch_id):
    """Write a batch of game updates to the database."""
    if df_batch.isEmpty():
        return

    pool = get_pool()
    conn = pool.getconn()
    cursor = conn.cursor()

    try:
        rows = df_batch.collect()
        for row in rows:
            cursor.execute("""
                INSERT INTO games (game_id, league, home_team, home_team_name, home_id, away_team, away_team_name, away_id, home_score, away_score, period, clock, status, status_detail, start_time, last_updated)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (game_id) DO UPDATE SET
                    league = EXCLUDED.league,
                    home_score = EXCLUDED.home_score,
                    away_score = EXCLUDED.away_score,
                    status = EXCLUDED.status,
                    status_detail = EXCLUDED.status_detail,
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
                row.period,
                row.clock,
                row.status,
                row.status_detail,
                row.start_time
            ))
        conn.commit()

        cache.publish("scorestream.updates", json.dumps({
            "type": "games",
            "batch_id": batch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

        print(f"[spark-games] Batch {batch_id} - Processed {len(rows)} records")
    except Exception as e:
        print(f"[spark-games] Games batch {batch_id} ERROR: {e}")
        print(traceback.format_exc())  
        conn.rollback()
    finally:
        cursor.close()
        pool.putconn(conn)

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
        
    df_goals = games_w_goals.select(
        col("game_id"), 
        explode(col("goals")).alias("goal")
    ).select(
            col("game_id"),
            col("goal.league").alias("league"), 
            col("goal.player_id").alias("player_id"), 
            col("goal.player_name").alias("player_name"), 
            col("goal.team_id").alias("team_id"),
            col("goal.minute").alias("minute"),
            col("goal.seconds").alias("seconds"),
            col("goal.goal_type").alias("goal_type"),
            col("goal.own_goal").alias("own_goal"),
            col("goal.penalty_goal").alias("penalty_goal")
    )

    pool = get_pool()
    conn = pool.getconn()
    cursor = conn.cursor()

    try:
        rows = df_goals.collect()

        for row in rows:
            cursor.execute("""
                INSERT INTO goals (game_id, league, player_id, player_name, team_id, minute, seconds, goal_type, own_goal, penalty_goal)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (game_id, player_id, minute, goal_type) DO UPDATE SET
                    goal_type = EXCLUDED.goal_type,
                    minute = EXCLUDED.minute,
                    league = EXCLUDED.league
            """, (
                row.game_id,
                row.league,
                row.player_id,
                row.player_name,
                row.team_id,
                row.minute,
                row.seconds,
                row.goal_type,
                row.own_goal,
                row.penalty_goal
            ))
        conn.commit()

        cache.publish("scorestream.updates", json.dumps({
            "type": "goals",
            "batch_id": batch_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))

        print(f"[spark-goals] Batch {batch_id} - Processed {len(rows)} goal records")
    except Exception as e:
        print(f"[spark-goals] Batch {batch_id} - Error processing goals batch: {e}")
        conn.rollback()
    finally:
        cursor.close()
        pool.putconn(conn)

scores_query = df_scores.writeStream \
    .foreachBatch(process_games) \
    .outputMode("update") \
    .option("checkpointLocation", "/app/checkpoints/scores") \
    .trigger(processingTime="5 seconds") \
    .start()

time.sleep(5)  # slight delay to stagger the queries and avoid DB contention on startup

goals_query = df_scores.writeStream \
    .foreachBatch(process_goals) \
    .outputMode("update") \
    .option("checkpointLocation", "/app/checkpoints/goals") \
    .trigger(processingTime="5 seconds") \
    .start()

print("[spark] Streaming queries started")
spark.streams.awaitAnyTermination()