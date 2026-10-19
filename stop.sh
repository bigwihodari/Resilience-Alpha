#!/usr/bin/env bash
# Resilience-Alpha — ARRÊTE TOUT (host principal/secours + client + attaquant).
# Les données (volumes) sont conservées. Git Bash / Linux / Mac.
echo "[..] Arrêt du serveur HOST..."
docker compose down 2>/dev/null || true
echo "[..] Arrêt du host de secours (si présent)..."
docker compose -f docker-compose.backup.yml down 2>/dev/null || true
echo "[..] Arrêt de l'app client (si présente)..."
docker compose -f client/docker-compose.yml down 2>/dev/null || true
echo "[..] Arrêt de la console attaquant (si présente)..."
docker compose -f attacker/docker-compose.yml down 2>/dev/null || true
echo "[ok] Tout est arrêté (les données sont conservées)."
echo "    Pour effacer aussi les données : docker compose down -v (par stack)."
