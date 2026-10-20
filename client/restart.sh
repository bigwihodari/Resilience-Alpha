#!/usr/bin/env bash
# App Client - REDEMARRE en appliquant le .env (apres modif des IP serveur).
set -e
echo "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
echo "[ok] App client redemarree."
docker compose ps
