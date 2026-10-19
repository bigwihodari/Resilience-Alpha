#!/usr/bin/env bash
# Chaos engineering — injecte une défaillance (arrêt brutal d'un conteneur) et
# vérifie la reprise automatique (politique restart + vérification canari).
# Usage : ./scripts/chaos.sh [service]   (défaut : ra-api)
set -u
TARGET="${1:-ra-api}"
INTERNAL="${INTERNAL_TOKEN:-internal-trusted-token}"
API=http://localhost:8000; AUTH=http://localhost:8001

canary(){
  local tok code
  tok=$(curl -s $AUTH/login -H 'Content-Type: application/json' -H "X-Internal-Token: $INTERNAL" \
        -d '{"username":"alice","password":"password123"}' \
        | python -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))" 2>/dev/null)
  [ -n "$tok" ] || return 1
  code=$(curl -s -o /dev/null -w '%{http_code}' $API/transactions -H "Authorization: Bearer $tok" \
        -H 'Content-Type: application/json' -d '{"amount":1,"recipient":"CHAOS"}')
  [ "$code" = "200" ]
}

echo "=== CHAOS ENGINEERING : arrêt brutal de $TARGET ==="
echo "-- Avant --"; canary && echo "  service OK" || echo "  service KO"
echo "-- Injection : docker kill $TARGET --"; docker kill "$TARGET" >/dev/null 2>&1
sleep 2
echo "-- Pendant --"; canary && echo "  service encore OK" || echo "  service indisponible (attendu)"
echo "-- Attente de la reprise automatique --"
for i in $(seq 1 20); do
  sleep 3
  if canary; then echo "  ✅ service RÉTABLI automatiquement après ~$((i*3))s"; exit 0; fi
done
echo "  ❌ non rétabli dans le délai"; exit 1
