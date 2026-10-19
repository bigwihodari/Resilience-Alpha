#!/usr/bin/env bash
# Resilience-Alpha — mise à jour du SERVEUR HOST. Git Bash / Linux / Mac.
# git pull + reconstruction/redémarrage propre (même si la stack tourne déjà).
set -e
echo "[..] Récupération du code (git pull)..."
git pull
if [ ! -f .env ]; then cp .env.example .env; echo "[ok] .env créé"; fi
getv() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true; }
ROLE=$(getv ROLE); ROLE=${ROLE:-primary}
echo "[..] Reconstruction et redémarrage (rôle : $ROLE)..."
docker compose up -d --build --remove-orphans
echo ""
echo "[ok] Serveur HOST à jour (rôle : $ROLE). État :"
docker compose ps
