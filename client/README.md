# 👤 App Client — Resilience-Alpha

Application à installer sur un **poste client** (CLIENT-A, CLIENT-B). Elle ne contient
que l'essentiel pour l'utilisateur : **connexion, recherche d'amis, paiement**. Le
cockpit et les KPI restent sur le serveur HOST.

## Lancer
```bash
cp .env.example .env     # régler HOST_PRIMARY (adresse du serveur HOST)
./start.sh               # ou .\start.ps1
```
App : http://localhost:8095 — connexion `alice` ou `bob` / `password123`.

## Configurer le serveur (`.env`)
| Variable | Local | Labo |
|---|---|---|
| `HOST_PRIMARY` | `host.docker.internal` | `192.168.137.1` |
| `HOST_BACKUP` | `host.docker.internal` | `192.168.137.2` (bascule, P14) |

## Résilience
Chaque paiement porte une **clé d'idempotence** : si le serveur tombe pendant la
transaction, l'app **ré-essaie avec la même clé** — la transaction est reprise et
appliquée **exactement une fois** (pas de double débit). La bascule automatique vers
le serveur de secours est ajoutée en P14.
