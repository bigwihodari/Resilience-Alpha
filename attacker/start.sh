#!/usr/bin/env bash
# Console Attaquant — lancement (Git Bash / Linux / Mac)
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[ok] .env créé. >> Édite TARGET_URL / TARGET_HOST si tu vises un autre poste."
fi

docker compose up -d --build

getv() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true; }
PORT=$(getv ATTACKER_PORT); PORT=${PORT:-8090}
TARGET=$(getv TARGET_URL); TARGET=${TARGET:-http://host.docker.internal:8080}

cat <<EOF

===================================================================
  CONSOLE ATTAQUANT lancée.
   >> Console (tout-en-un) : http://localhost:$PORT
   >> Cible configurée     : $TARGET
===================================================================
EOF
