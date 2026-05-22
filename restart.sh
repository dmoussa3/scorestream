#!/bin/bash
echo "Shutting down ScoreStream..."
docker compose down

echo "Waiting for containers to fully stop..."
sleep 10  # increased from 5 to 10

echo "Verifying spark container is stopped..."
while docker ps | grep -q scorestream-spark; do
    echo "Spark still running, waiting..."
    sleep 2
done

echo "Clearing Spark checkpoints (including hidden files)..."
find checkpoints/scores -mindepth 1 -delete
find checkpoints/standings -mindepth 1 -delete
find checkpoints/goals -mindepth 1 -delete

touch checkpoints/scores/.gitkeep
touch checkpoints/standings/.gitkeep
touch checkpoints/goals/.gitkeep

echo "Starting ScoreStream..."
docker compose up