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
| `detector` | détection d'anomalie ML | Isolation Forest | ✅ P4 |
| `traffic-gen` | trafic légitime randomisé (baseline ML) | Python | ✅ P3 |
| `attacker` | **app attaquant tout-en-un** (console + KPIs) | FastAPI + Chart.js | ✅ P3 |
| `orchestrator` | moteur de remédiation (zero-touch) | FastAPI + Ansible | ⏳ P5 |
| WAF applicatif | filtrage des entrées (SQLi/XSS) dans `auth`+`api` | signatures OWASP | ✅ P7 |
| SIEM / SOC | fonction SOC intégrée (Loki + Prometheus + cockpit) | — | ✅ P7 |
| Secrets | gestion chiffrée | SOPS + age | ✅ P7 (workflow) |
| `assistant` | assistant RAG opérateur (lecture doc) | Ollama (qwen3:8b) + LangChain + FAISS | ✅ P8 |

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
./stop.sh                    # arrête TOUT (host + backup + client + attaquant) — ou .\stop.ps1
docker compose down          # arrête seulement ce dossier (garde les données)
docker compose down -v       # arrête ET supprime les données de cette stack
```

## Haute disponibilité (montage 5 PC)

Topologie : **2 serveurs** (principal + secours), **2 clients**, **1 attaquant**.
- L'**app client** (dossier [`client/`](client/README.md)) connecte les clients au serveur ;
  ils se paient en direct (transfert + annuaire).
- Le **backup** réplique le principal (comptes + clés d'idempotence) ; si le principal
  tombe, **le client bascule tout seul** sur le backup et une **transaction en cours est
  reprise sans double débit** (clé d'idempotence).
- Détail et réglages : [`DEPLOIEMENT.md`](DEPLOIEMENT.md) §8 · recette : `scripts/recette-ha.sh`.

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

Détail complet dans [`SECURITE.md`](SECURITE.md). En bref :
- **WAF applicatif** (SQLi/XSS) sur `auth` et `api` → blocage 403 + métrique + log.
- **Fonction SOC** intégrée (Loki + Prometheus + vue SOC du cockpit).
- **Deux réponses distinctes** : DoS → bouclier (disponibilité) ; injection SQL →
  WAF + contrôle d'intégrité (compromission).
- **Moindre privilège** : orchestrateur via API d'admin scoped (token dédié), pas
  d'accès god-mode aux conteneurs.
- Base de données **non exposée** ; `no-new-privileges` sur les services.
- **Secrets chiffrés via SOPS + age** ; `.env` jamais committé.

## Gouvernance

Analyse de risques et conformité, reliées à l'architecture réelle (dossier) :
- [EBIOS RM](docs/gouvernance/ebios-rm.md) · [PCA/PRA](docs/gouvernance/pca-pra.md) ·
  [NIS2/DORA](docs/gouvernance/nis2-dora.md) · [synthèse direction](docs/gouvernance/README.md)

## Dépôt

https://github.com/bigwihodari/Resilience-Alpha
