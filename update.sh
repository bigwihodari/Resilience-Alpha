#!/usr/bin/env bash
# Resilience-Alpha — mise à jour (Git Bash / Linux / Mac)
# Récupère le code, reconstruit et redémarre proprement, même si la stack tourne déjà.
set -e

echo "[..] Récupération du code (git pull)..."
git pull

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[ok] .env créé depuis .env.example"
fi

echo "[..] Reconstruction et redémarrage des conteneurs modifiés..."
docker compose up -d --build --remove-orphans

echo ""
echo "[ok] Mise à jour terminée. État :"
docker compose ps
