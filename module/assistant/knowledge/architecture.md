# Architecture du module Resilience Guard

Resilience Guard est une brique de sécurité « plug-and-protect » qui se pose devant
n'importe quelle application web, sans modifier son code. Le trafic entre par la
**passerelle** (reverse-proxy), qui applique le WAF, le load-shedding et exporte les
métriques, puis est relayé vers l'application protégée (`PROTECTED_UPSTREAM`).

## Composants

- **gateway** (port 8080) : reverse-proxy FastAPI + httpx. WAF applicatif, bouclier
  anti-DoS (load-shedding), proxy vers l'amont, export Prometheus. C'est le seul point
  d'entrée. Endpoints de gestion : `GET /health`, `GET /metrics`, `POST /admin/protect`.
- **prometheus** (port 9090) : collecte les métriques de la passerelle, du détecteur et
  des conteneurs (cAdvisor). Intervalle de scrape 5 s.
- **grafana** (port 3000) : tableaux de bord d'observabilité. Loki pour les logs.
- **loki + promtail** : agrégation des logs de tous les conteneurs.
- **cadvisor** : métriques CPU / mémoire des conteneurs (exposé en interne uniquement).
- **detector** : détection d'anomalies par Isolation Forest + distance standardisée,
  sur les métriques de la passerelle. Expose `anomaly_score` (0-100) et `anomaly_flag`.
- **orchestrator** : moteur de remédiation autonome. Surveille le détecteur et le WAF,
  active le bouclier, exécute un canari de vérification, tient une timeline.
- **assistant** : assistant RAG local (Ollama + LangChain + FAISS), lecture seule.
- **cockpit** (port 8088) : tableau de bord unique (santé, KPI, détection, remédiation,
  WAF, assistant).

## Métriques clés (noms Prometheus)

- `http_requests_total{status}` — débit par classe de statut (2xx, 4xx, 5xx).
- `http_request_duration_seconds_bucket` — histogramme de latence (p95 via `histogram_quantile`).
- `waf_blocked_total{rule}` — requêtes bloquées par le WAF, par règle.
- `anomaly_score`, `anomaly_flag`, `detector_trained` — détection ML.
- `remediation_active` — 1 si le bouclier de remédiation est actif.
