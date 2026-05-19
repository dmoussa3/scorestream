#!/bin/bash
echo "Shutting down ScoreStream..."
docker compose down

echo "Waiting for containers to fully stop..."
sleep 5

echo "Clearing Spark checkpoints (including hidden files)..."
rm -rf checkpoints/scores/*
rm -rf checkpoints/standings/*
rm -rf checkpoints/goals/*
mkdir -p checkpoints/scores/
mkdir -p checkpoints/standings/
mkdir -p checkpoints/goals/

touch checkpoints/scores/.gitkeep                                
touch checkpoints/standings/.gitkeep
touch checkpoints/goals/.gitkeep

echo "Starting ScoreStream..."
docker compose up