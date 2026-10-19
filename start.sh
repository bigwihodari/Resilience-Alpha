#!/usr/bin/env bash
# Resilience-Alpha — lancement rapide (Git Bash / Linux / Mac)
set -e

if [ ! -f .env ]; then
  cp .env.example .env
  echo "[ok] .env créé depuis .env.example"
fi

echo "[..] Construction et démarrage des conteneurs..."
docker compose up -d --build

getport() { grep -E "^$1=" .env 2>/dev/null | head -1 | cut -d= -f2 | tr -d '[:space:]' || true; }
FRONT=$(getport FRONTEND_PORT); FRONT=${FRONT:-8080}
API=$(getport API_PORT); API=${API:-8000}
GRAF=$(getport GRAFANA_PORT); GRAF=${GRAF:-3000}
PROM=$(getport PROMETHEUS_PORT); PROM=${PROM:-9090}

cat <<EOF

===================================================================
  RESILIENCE-ALPHA (poste HÔTE) est lancé.
  >> TOUT est accessible depuis l'application de paiement :
       http://localhost:$FRONT       (connexion : alice / password123)

  Panels (aussi listés dans le Hub de l'application) :
   - Paiement / Hub ....... http://localhost:$FRONT
   - Cockpit résilience .... http://localhost:$FRONT/cockpit
   - API (Swagger) ......... http://localhost:$API/docs
   - Grafana ............... http://localhost:$GRAF   (admin / admin)
   - Prometheus ............ http://localhost:$PROM/targets
   - Logs (Loki) ........... http://localhost:$GRAF/explore
===================================================================
EOF
