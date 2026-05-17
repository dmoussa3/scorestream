#!/bin/bash
echo "Shutting down ScoreStream..."
docker compose down

echo "Clearing Spark checkpoints..."
rm -rf checkpoints/scores/*
rm -rf checkpoints/standings/*
rm -rf checkpoints/goals/*
mkdir -p checkpoints/scores/
mkdir -p checkpoints/standings/
mkdir -p checkpoints/goals/
touch checkpoints/scores/.gitkeep                                
touch checkpoints/standings/.gitkeep
touch checkpoints/goals/.gitkeep