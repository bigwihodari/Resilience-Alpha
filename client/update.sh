#!/usr/bin/env bash
# App Client — mise à jour. Git Bash / Linux / Mac.
set -e
echo "[..] git pull..."; git pull
docker compose up -d --build
echo "[ok] App client à jour."
docker compose ps
