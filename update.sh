#!/usr/bin/env bash
# Resilience-Alpha — mise à jour COMPLÈTE (host + client + attaquant). Git Bash / Linux / Mac.
# git pull + reconstruction + recréation forcée (sinon un changement de conf nginx/env
# n'est pas toujours appliqué par `up --build` seul).
set -e
cd "$(dirname "$0")"
echo "[..] Récupération du code (git pull)..."
git pull --ff-only || git pull
[ -f .env ] || { cp .env.example .env; echo "[ok] .env créé"; }

echo "[..] HOST (api / auth / frontend / orchestrateur / observabilité)..."
docker compose up -d --build --force-recreate --remove-orphans

if [ -d client ]; then
  echo "[..] CLIENT (le jeu)..."
  ( cd client && docker compose up -d --build --force-recreate )
fi
if [ -d attacker ]; then
  echo "[..] ATTAQUANT (console)..."
  ( cd attacker && docker compose up -d --build --force-recreate )
fi

echo ""
echo "[ok] Tout est à jour. État du host :"
docker compose ps
echo ""
echo "Jeu (client)   : http://localhost:8095"
echo "App / cockpit  : http://localhost:8080"
echo "Console attaq. : http://localhost:8090"
