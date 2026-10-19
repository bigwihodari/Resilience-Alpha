# PROJECT RESILIENCE-ALPHA

Prototype de **cyber-résilience à reprise autonome** pour une plateforme de
paiement fictive (Workshop EPSI Bac+5). Le système subit une attaque contrôlée,
la **détecte par machine learning**, se **remédie sans intervention humaine**, et
le **prouve** en rejouant une transaction.

> ⚠️ Environnement, données et attaques **entièrement fictifs**, strictement
> limités au labo de l'équipe. Aucune donnée bancaire réelle.

## Architecture (en cours de construction)

| Service | Rôle | Techno | État |
|---|---|---|---|
| `db` | base de données (comptes, transactions) | PostgreSQL 16 | ✅ P1 |
| `auth` | authentification, émission de JWT | FastAPI | ✅ P1 |
| `api` | API de paiement (transactions fictives) | FastAPI | ✅ P1 |
| `frontend` | UI paiement + cockpit + console attaque | React + Tailwind (nginx) | ✅ P1 (paiement) |
| `prometheus` / `grafana` / `loki` / `promtail` / `cadvisor` | observabilité (métriques, logs, CPU/mém) | Prometheus, Grafana, Loki | ✅ P2 |
| `detector` | détection d'anomalie ML | Isolation Forest | ⏳ P4 |
| `traffic-gen` | trafic légitime randomisé (baseline ML) | Python | ✅ P3 |
| `attacker` | **app attaquant tout-en-un** (console + KPIs) | FastAPI + Chart.js | ✅ P3 |
| `orchestrator` | moteur de remédiation (zero-touch) | FastAPI + Ansible | ⏳ P5 |
| `detector` | détection d'anomalie ML | Isolation Forest | ⏳ P4 |
| `waf` | pare-feu applicatif | Traefik + Coraza | ⏳ P7 |
| `assistant` | assistant RAG | Ollama + LangChain | ⏳ P8 |

> 📖 **Nouvelle machine / équipe ?** Guide pas-à-pas détaillé dans
> [`DEPLOIEMENT.md`](DEPLOIEMENT.md).

## Prérequis

- Docker Desktop (WSL2) démarré
- 16 Go de RAM recommandés

## Démarrer

```bash
cp .env.example .env         # adapter si besoin
docker compose up -d --build
```

Ou, plus simple, le script tout-en-un : `./start.sh` (Git Bash) ou `.\start.ps1` (PowerShell).

Accès :
- **Frontend (paiement)** : http://localhost:8080  (démo : `alice` / `password123`)
- **API** : http://localhost:8000  (`/docs` pour Swagger)
- **Auth** : http://localhost:8001
- **Grafana** : http://localhost:3000  (`admin` / `admin`, datasources + dashboard auto-provisionnés)
- **Prometheus** : http://localhost:9090  (`/targets` pour voir les cibles)
- **cAdvisor** : http://localhost:8081

## Vérifier (chaîne login → paiement)

```bash
# 1. Connexion → récupère un JWT
TOKEN=$(curl -s localhost:8001/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"password123"}' | python -c "import sys,json;print(json.load(sys.stdin)['access_token'])")

# 2. Solde
curl -s localhost:8000/accounts/me -H "Authorization: Bearer $TOKEN"

# 3. Payer 50 €
curl -s localhost:8000/transactions -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"amount":50,"recipient":"MERCHANT-01"}'

# 4. Historique
curl -s localhost:8000/transactions -H "Authorization: Bearer $TOKEN"
```

## Arrêter

```bash
docker compose down          # garde les données
docker compose down -v       # supprime aussi la base
```

## Poste Attaquant (application séparée)

L'attaque se lance depuis une **application unique** dédiée, dans `attacker/`
(à exécuter sur un PC distinct en conditions réelles) :

```bash
cd attacker
cp .env.example .env     # régler TARGET_URL / TARGET_HOST
./start.sh               # ou .\start.ps1
```

Console (tout-en-un) : http://localhost:8090 — voir [`attacker/README.md`](attacker/README.md).

## Sécurité

- La base de données n'est **pas** exposée au réseau.
- Les secrets passeront par **SOPS** (phase Cyber) ; `.env` n'est jamais committé.
- Le moteur de remédiation aura des droits **restreints** (docker-socket-proxy).

## Dépôt

https://github.com/bigwihodari/Resilience-Alpha
