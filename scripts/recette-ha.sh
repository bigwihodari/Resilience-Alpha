#!/usr/bin/env bash
# Recette HA — vérifie la bascule automatique et la reprise d'une transaction.
# Prérequis : stack principale + host de secours (docker-compose.backup.yml) + app client.
# ATTENTION : arrête puis redémarre le principal (ra-api, ra-auth).
set -u
IT="${INTERNAL_TOKEN:-internal-trusted-token}"
C=http://localhost:8095          # app client (bascule nginx)
PASS=0; FAIL=0
ok(){ echo "  [OK] $1"; PASS=$((PASS+1)); }
ko(){ echo "  [KO] $1"; FAIL=$((FAIL+1)); }
pyget(){ python -c "import sys,json
try:
    print(json.load(sys.stdin)$1)
except Exception:
    print('')"; }
login(){ curl -s $C/auth/login -H 'Content-Type: application/json' -H "X-Internal-Token: $IT" \
         -d '{"username":"alice","password":"password123"}' | pyget "['access_token']"; }
pay(){ curl -s $C/api/transactions -H "Authorization: Bearer $1" -H 'Content-Type: application/json' \
       -d "{\"amount\":$2,\"recipient\":\"bob\",\"idempotency_key\":\"$3\"}"; }

echo "=== RECETTE HA — bascule & reprise ==="
echo "-- 1. Serveurs & client présents --"
for c in ra-api ra-auth ra-api-backup ra-auth-backup ra-client; do
  [ "$(docker inspect -f '{{.State.Status}}' $c 2>/dev/null)" = running ] && ok "$c" || ko "$c (absent)"
done
TOK=$(login); [ -n "$TOK" ] && ok "login via l'app client" || ko "login via l'app client"

echo "-- Préparation : backup en réplication active (reset du verrou de promotion) --"
docker restart ra-api-backup >/dev/null 2>&1
REPL_OK=""
for i in $(seq 1 20); do
  sleep 2
  S=$(curl -s localhost:8010/repl/status)
  p=$(echo "$S" | pyget "['promoted']"); ls=$(echo "$S" | pyget "['last_sync']")
  if [ "$p" = "False" ] && [ -n "$ls" ] && [ "$ls" != "None" ]; then REPL_OK=1; break; fi
done
[ -n "$REPL_OK" ] && ok "backup en réplication active" || ko "backup non réplicant"

echo "-- 2. Paiement nominal (via principal) --"
R=$(pay "$TOK" 5 "HA-K1"); [ "$(echo "$R" | pyget "['status']")" = completed ] && ok "paiement HA-K1" || ko "paiement HA-K1 : $R"
echo "   (réplication de HA-K1 vers le backup…)"; sleep 4

echo "-- 3. Crash du principal --"
docker stop ra-api ra-auth >/dev/null 2>&1; sleep 3; ok "principal arrêté (crash simulé)"

echo "-- 4. Bascule automatique (client -> backup) --"
TOK2=$(login); [ -n "$TOK2" ] && ok "login pendant le crash (via backup)" || ko "login indisponible pendant le crash"
R=$(pay "$TOK2" 5 "HA-K1"); [ "$(echo "$R" | pyget "['resumed']")" = "True" ] && ok "reprise HA-K1 = resumed (pas de double débit)" || ko "reprise HA-K1 : $R"
R=$(pay "$TOK2" 3 "HA-K2"); [ "$(echo "$R" | pyget "['status']")" = completed ] && ok "nouveau paiement HA-K2 via backup (service maintenu)" || ko "paiement HA-K2 : $R"

echo "-- 5. Restauration du principal --"
docker start ra-api ra-auth >/dev/null 2>&1; ok "principal redémarré"

echo ""
echo "=== RÉSULTAT HA : $PASS OK / $FAIL KO ==="
[ "$FAIL" = 0 ] && echo "✅ RECETTE HA VERTE" || echo "❌ des vérifications ont échoué"
exit $FAIL
