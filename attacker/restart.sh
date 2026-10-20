#!/usr/bin/env bash
# Console Attaquant - REDEMARRE en appliquant le .env (apres modif de la cible).
set -e
echo "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
echo "[ok] Console attaquant redemarree."
docker compose ps
