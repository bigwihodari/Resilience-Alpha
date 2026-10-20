#!/usr/bin/env bash
# Resilience-Alpha - REDEMARRE le serveur HOST en appliquant le .env.
# A utiliser apres avoir modifie des valeurs (IP, ports, ROLE, PEER_API_URL...).
set -e
echo "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
echo "[ok] Redemarre."
docker compose ps
