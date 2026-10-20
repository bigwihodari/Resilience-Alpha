#!/usr/bin/env bash
# App Client — reconstruction complète (temps réel / WebSocket).
# Git Bash / Linux / Mac. À lancer depuis le dossier client/.
set -e
cd "$(dirname "$0")"

echo "[1/4] Mise à jour du code (git pull)..."
git pull

echo "[2/4] Pré-téléchargement des images de base..."
docker pull node:20-alpine
docker pull nginx:1.27-alpine

echo "[3/4] Reconstruction de l'app client..."
docker compose up -d --build

echo "[4/4] État des conteneurs :"
docker compose ps

# Vérification du WebSocket : un handshake réussi renvoie "101".
# Le port de l'app client est lu dans .env (CLIENT_PORT), défaut 8095.
PORT=8095
if [ -f .env ]; then
  P=$(grep -E '^\s*CLIENT_PORT\s*=\s*[0-9]+' .env | head -1 | sed -E 's/[^0-9]//g')
  [ -n "$P" ] && PORT="$P"
fi

echo ""
echo "Vérification du WebSocket (/ws) sur le port $PORT..."
LINE=$(curl -s -i -N \
  -H "Connection: Upgrade" -H "Upgrade: websocket" \
  -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==" \
  "http://localhost:$PORT/ws" 2>/dev/null | grep -i '^HTTP' | head -1 | tr -d '\r')

if echo "$LINE" | grep -q "101"; then
  echo "[ok] WebSocket actif : $LINE"
else
  echo "[!!] Réponse inattendue : $LINE"
  echo "     (le serveur hôte est-il bien lancé et joignable ?)"
fi

echo ""
echo "Terminé. Ouvre l'app client, fais un paiement depuis l'autre client :"
echo "le solde doit se mettre à jour tout seul, sans rafraîchir la page."
