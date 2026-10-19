# Architecture — Resilience-Alpha

## Composants
- `frontend` (React + Tailwind, servi par nginx) : application unique du poste Hôte —
  paiement + cockpit de supervision. nginx fait aussi reverse-proxy vers auth, api,
  Prometheus et l'orchestrateur.
- `api` (FastAPI) : traite les transactions fictives ; expose /metrics ; WAF applicatif.
- `auth` (FastAPI) : authentification JWT ; mode bouclier anti-DoS ; WAF applicatif.
- `db` (PostgreSQL) : comptes et transactions fictifs ; non exposée au réseau.
- `detector` (Python/scikit-learn) : détection d'anomalies ML, score exposé à Prometheus.
- `orchestrator` (FastAPI) : moteur de remédiation (détecte → décide → agit → vérifie).
- Observabilité : `prometheus` (métriques), `grafana` (dashboards), `loki` + `promtail`
  (logs), `cadvisor` (CPU/mémoire conteneurs).
- `traffic-gen` : trafic légitime continu (baseline du modèle ML).
- `assistant` (ce module) : RAG local (Ollama + LangChain) ; lecture de la doc seulement.
- Poste attaquant (`attacker/`, application séparée) : lance DoS et injection SQL.

## Flux de résilience
trafic + attaque → métriques Prometheus + logs Loki → détecteur ML (score) →
orchestrateur (décision + action) → vérification par transaction canari → cockpit.

## Réseau
Les deux postes (Hôte, Attaquant) communiquent via le point d'accès Wi-Fi du groupe
(RESILIENCE-G<n>, 192.168.137.x). La base de données, les secrets et les interfaces
internes ne sont pas exposés au réseau pédagogique.

## Technologies
React/Tailwind, FastAPI (Python), PostgreSQL, Docker Compose, Prometheus/Grafana/Loki,
scikit-learn (Isolation Forest), Ollama + LangChain (RAG), WAF applicatif, SOPS (secrets).
