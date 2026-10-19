#!/usr/bin/env bash
# Resilience-Alpha — SERVEUR HOST (principal ou secours). Git Bash / Linux / Mac.
set -e
if [ ! -f .env ]; then cp .env.example .env; echo "[ok] .env créé depuis .env.example"; fi
getv() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true; }
ROLE=$(getv ROLE); ROLE=${ROLE:-primary}
PEER=$(getv PEER_API_URL)
if [ "$ROLE" = "backup" ] && [ -z "$PEER" ]; then
  echo "[!] ROLE=backup mais PEER_API_URL est vide dans .env (ex. http://192.168.137.1:8000)."
fi

echo "[..] Démarrage du serveur HOST (rôle : $ROLE)..."
docker compose up -d --build

FRONT=$(getv FRONTEND_PORT); FRONT=${FRONT:-8080}
API=$(getv API_PORT); API=${API:-8000}
GRAF=$(getv GRAFANA_PORT); GRAF=${GRAF:-3000}
PROM=$(getv PROMETHEUS_PORT); PROM=${PROM:-9090}
cat <<EOF

===================================================================
  RESILIENCE-ALPHA — SERVEUR HOST (rôle : $ROLE) lancé.
  >> Cockpit / supervision :  http://localhost:$FRONT
   - Cockpit ........... http://localhost:$FRONT/cockpit
   - API (Swagger) ..... http://localhost:$API/docs
   - Grafana ........... http://localhost:$GRAF   (admin / admin)
   - Prometheus ........ http://localhost:$PROM/targets
EOF
[ "$ROLE" = "backup" ] && echo "   - Réplique le principal : ${PEER:-<non configuré>}"
echo "==================================================================="
