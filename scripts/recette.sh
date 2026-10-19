#!/usr/bin/env bash
# Recette automatisée — vérifie la chaîne de cyber-résilience de bout en bout.
# Usage : ./scripts/recette.sh   (Git Bash / Linux / Mac, depuis la racine du projet)
set -u
INTERNAL="${INTERNAL_TOKEN:-internal-trusted-token}"
FRONT=http://localhost:8080; API=http://localhost:8000; AUTH=http://localhost:8001; ATT=http://localhost:8090
PASS=0; FAIL=0
ok(){ echo "  [OK] $1"; PASS=$((PASS+1)); }
ko(){ echo "  [KO] $1"; FAIL=$((FAIL+1)); }

pyget(){ python -c "import sys,json
try:
    d=json.load(sys.stdin); print(eval('d'+'''$1'''))
except Exception:
    print('')"; }
orch(){ curl -s $FRONT/orch/status; }
canary(){
  local tok code
  tok=$(curl -s $AUTH/login -H 'Content-Type: application/json' -H "X-Internal-Token: $INTERNAL" \
        -d '{"username":"alice","password":"password123"}' | pyget "['access_token']")
  [ -n "$tok" ] || return 1
  code=$(curl -s -o /dev/null -w '%{http_code}' $API/transactions -H "Authorization: Bearer $tok" \
        -H 'Content-Type: application/json' -d '{"amount":1,"recipient":"RECETTE"}')
  [ "$code" = "200" ]
}

echo "=== RECETTE Resilience-Alpha ==="

echo "-- 1. Santé des services --"
for c in ra-db ra-auth ra-api ra-frontend ra-detector ra-orchestrator ra-attacker; do
  [ "$(docker inspect -f '{{.State.Status}}' $c 2>/dev/null)" = running ] && ok "$c" || ko "$c (absent/arrêté)"
done

echo "-- 2. Détecteur ML entraîné --"
tr=$(curl -s "http://localhost:9090/api/v1/query?query=detector_trained" | pyget "['data']['result'][0]['value'][1]")
[ "$tr" = "1" ] && ok "modèle ML entraîné" || ko "modèle ML non entraîné"

echo "-- 3. Service nominal (transaction canari) --"
canary && ok "transaction nominale réussie" || ko "transaction nominale échouée"

echo "-- 4. Attaque DoS → détection + remédiation autonome --"
curl -s -X POST $ATT/api/attack/start -H 'Content-Type: application/json' \
     -d '{"type":"dos","intensity":30,"duration":50}' -o /dev/null
state=""
for i in $(seq 1 16); do state=$(orch | pyget "['state']"); [ "$state" = RECOVERED ] && break; sleep 3; done
[ "$state" = RECOVERED ] && ok "reprise autonome (état RECOVERED)" || ko "pas de reprise auto (état=$state)"
[ "$(orch | pyget "['protection']")" = True ] && ok "bouclier anti-DoS actif" || ko "bouclier inactif"
canary && ok "transaction RÉUSSIE pendant l'attaque (service utilisable)" || ko "service indisponible pendant l'attaque"
curl -s -X POST $ATT/api/attack/stop -o /dev/null

echo "-- 5. Injection SQL → WAF + contrôle d'intégrité --"
curl -s -X POST $ATT/api/attack/start -H 'Content-Type: application/json' \
     -d '{"type":"sqli","intensity":5,"duration":20}' -o /dev/null
sec=""
for i in $(seq 1 9); do sec=$(orch | pyget "['security_state']"); [ "$sec" = CONTAINED ] && break; sleep 3; done
[ "$sec" = CONTAINED ] && ok "injection contenue par le WAF" || ko "injection non contenue (sec=$sec)"
[ "$(orch | pyget "['last_integrity']['integrity_ok']")" = True ] && ok "intégrité des données confirmée" || ko "intégrité non confirmée"
curl -s -X POST $ATT/api/attack/stop -o /dev/null

echo "-- 6. Transaction finale (après incidents) --"
canary && ok "transaction finale réussie" || ko "transaction finale échouée"

echo ""
echo "=== RÉSULTAT : $PASS OK / $FAIL KO ==="
[ "$FAIL" = 0 ] && echo "✅ RECETTE VERTE" || echo "❌ des vérifications ont échoué"
exit $FAIL
