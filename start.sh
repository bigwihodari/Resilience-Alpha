#!/usr/bin/env bash
# Resilience-Alpha — lancement rapide (Git Bash / Linux / Mac)
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[ok] .env créé depuis .env.example"
fi

echo "[..] Construction et démarrage des conteneurs..."
docker compose up -d --build

echo ""
echo "[ok] Resilience-Alpha est lancé."
echo "     Frontend : http://localhost:8080   (alice / password123)"
echo "     API doc  : http://localhost:8000/docs"
