#!/usr/bin/env bash
# Console Attaquant — mise à jour. Git Bash / Linux / Mac.
set -e
echo "[..] git pull..."; git pull
docker compose up -d --build
echo "[ok] Console attaquant à jour."
docker compose ps
