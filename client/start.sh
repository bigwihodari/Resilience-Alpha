#!/usr/bin/env bash
# App Client — lancement (Git Bash / Linux / Mac)
set -e
if [ ! -f .env ]; then cp .env.example .env; echo "[ok] .env créé. >> Édite HOST_PRIMARY si besoin."; fi
docker compose up -d --build
getv() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true; }
PORT=$(getv CLIENT_PORT); PORT=${PORT:-8095}
H=$(getv HOST_PRIMARY); H=${H:-host.docker.internal}
cat <<EOF

===================================================================
  APP CLIENT lancée.
   >> http://localhost:$PORT    (login : alice ou bob / password123)
   >> Serveur cible : $H
===================================================================
EOF
