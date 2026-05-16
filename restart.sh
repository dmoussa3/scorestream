#!/bin/bash
echo "Shutting down ScoreStream..."
docker compose down

echo "Clearing Spark checkpoints..."
rm -rf checkpoints/scores/offsets
rm -rf checkpoints/standings/offsets
rm -rf checkpoints/goals/offsets
mkdir -p checkpoints/scores/offsets
mkdir -p checkpoints/standings/offsets
mkdir -p checkpoints/goals/offsets
touch checkpoints/scores/.gitkeep                                
touch checkpoints/standings/.gitkeep
touch checkpoints/goals/.gitkeep

echo "Starting ScoreStream..."
docker compose up