# 🛡️ Resilience Guard — module de sécurité & résilience « plug-and-protect »

Brique **réutilisable** qui se pose **devant n'importe quelle application web** et lui
ajoute, **sans toucher à son code**, tout l'arsenal défensif du projet :

- **WAF applicatif** (signatures type OWASP : SQLi, XSS…) → requêtes malveillantes bloquées (403).
- **KPI / observabilité automatiques** : débit, latence (p95), taux d'erreurs 4xx/5xx, CPU/mémoire des conteneurs, requêtes bloquées — exportés vers **Prometheus** + **Grafana** + **Loki** (logs).
- **Détection d'anomalies par IA (ML)** : Isolation Forest sur le trafic → score d'anomalie.
- **Remédiation autonome (zéro-touch)** : bouclier anti-DoS (load-shedding), transaction canari de vérification, contrôle d'intégrité — piloté par l'orchestrateur.
- **Haute disponibilité** : serveur de **secours** + bascule/retour automatiques.
- **Assistant IA (RAG)** : Ollama + LangChain + FAISS — répond aux questions d'exploitation sur la base de la doc/procédures.
- **Cockpit** : tableau de bord unique (santé, KPI, détection, remédiation, HA, menaces).

> C'est **la même techno** que la démo de paiement, mais **packagée pour s'installer partout**,
> **sans** les add-ons de jeu (livrets, shop, dino, attaquant…). Le jeu reste dans l'app d'origine ;
> ce module est le livrable de présentation.

---

## Comment ça s'installe (le principe « 1 commande »)

L'app à protéger tourne derrière la **passerelle** du module (reverse-proxy). On indique
une seule variable : l'URL amont de l'app (`PROTECTED_UPSTREAM`). On lance l'overlay :

```bash
# à côté de votre app (dockerisée ou non)
PROTECTED_UPSTREAM=http://mon-app:8000 \
docker compose -f docker-compose.module.yml up -d
# -> l'app est servie via la passerelle (port 8080), protégée + supervisée.
# Cockpit : http://localhost:8088   Grafana : http://localhost:3000
```

Pour une app **non-dockerisée**, `PROTECTED_UPSTREAM` peut pointer vers son URL (ex. `http://host.docker.internal:3000`).

---

## Architecture

```
          Internet / clients
                 │
                 ▼
     ┌───────────────────────┐   métriques (http_requests_total,
     │  gateway (WAF + proxy) │──  http_request_duration_seconds,
     │  exporte /metrics      │    waf_blocked_total) ─────────────┐
     └───────────┬───────────┘                                     ▼
                 │ proxy_pass                               ┌────────────┐
                 ▼                                          │ prometheus │
        PROTECTED_UPSTREAM                                  └─────┬──────┘
        (votre app, inchangée)                                    │
                                                    ┌─────────────┼───────────────┐
                                                    ▼             ▼               ▼
                                              ┌──────────┐  ┌──────────────┐  ┌─────────┐
                                              │ detector │  │ orchestrator │  │ grafana │
                                              │ (ML/IF)  │  │ (remédiation)│  │  loki   │
                                              └────┬─────┘  └──────┬───────┘  └─────────┘
                                                   │  anomalie     │ /admin/protect (bouclier)
                                                   ▼               ▼  → gateway
                                              ┌───────────────────────────┐   ┌───────────┐
                                              │  cockpit (dashboard)      │   │ assistant │
                                              │  + HA (gateway/app secours)│  │ (RAG/Ollama)│
                                              └───────────────────────────┘   └───────────┘
```

- La **passerelle** est le seul composant générique nouveau : elle fait le WAF, exporte les
  **mêmes noms de métriques** que l'app de démo (donc detector/prometheus/grafana marchent sans
  changement), et expose `/admin/protect` pour que l'orchestrateur active le bouclier.
- `detector`, `orchestrator`, `assistant`, `prometheus`, `grafana`, `loki` sont **réutilisés** du
  projet (copiés dans `module/` pour être autonomes) et pointés sur la passerelle.
- **HA** : une 2ᵉ passerelle (secours) + l'app secours ; bascule nginx + réconciliation (optionnel selon l'app).

---

## Contenu du dossier

```
module/
  README.md                    (ce fichier)
  docker-compose.module.yml    (overlay : gateway + stack défensive + cockpit)
  docker-compose.ha.yml        (overlay HA : 2e passerelle secours + bascule)
  .env.example                 (PROTECTED_UPSTREAM, ports, tokens, modèle LLM)
  gateway/                     (passerelle WAF + métriques — FastAPI + httpx)
  ha/                          (reverse-proxy nginx de bascule principal/secours)
  detector/ orchestrator/ assistant/   (réutilisés, pointés sur la gateway)
  prometheus/ grafana/ loki/   (configs d'observabilité ; prometheus-ha.yml pour la HA)
  cockpit/                     (dashboard du module, SANS jeu)
demo-apps/
  paiement/                    (démo de paiement SANS les add-ons de jeu)
  vitrine/                     (app VIERGE : petit site, pour montrer « install sur n'importe quoi »)
  README.md                    (lancer une démo + y brancher le module)
```

## Spéc de la passerelle (`gateway/`)
FastAPI + httpx. Pour chaque requête : (1) WAF sur path/query/corps (signatures SQLi/XSS → 403 +
`waf_blocked_total`), (2) load-shedding si bouclier actif (`/admin/protect`), (3) proxy vers
`PROTECTED_UPSTREAM`, (4) mesure latence + statut. Expose `/metrics` (Prometheus) avec
`http_requests_total{status}`, `http_request_duration_seconds_bucket`, `waf_blocked_total`,
et `/health`. Aucune dépendance à l'app protégée.

## Haute disponibilité (`docker-compose.ha.yml`)
Overlay qui ajoute une **2ᵉ passerelle de secours** (`gateway-backup`, même image, identité
`NODE_ID=backup`) derrière un **reverse-proxy nginx de bascule** (`ha/nginx.conf`). Ce proxy
devient le point d'entrée public (port 8080) : le principal sert, et sur panne (`error` /
`timeout` / `502` / `503` / `504`) nginx bascule **automatiquement** sur le secours
(`proxy_next_upstream`), puis y revient dès que le principal répond. Prometheus scrape les
**deux** passerelles (`prometheus/prometheus-ha.yml`). Le cockpit affiche la section
**« Haute disponibilité »** : quel nœud sert (via `/health` → `node`), santé principal/secours,
et une bannière quand la bascule est active.

```bash
cd module
docker compose -f docker-compose.module.yml -f docker-compose.ha.yml up -d --build
# démo bascule :
docker stop rg-gateway     # le service continue via le secours (cockpit : « bascule active »)
docker start rg-gateway    # retour automatique au principal
```

> L'orchestrateur pointe son canari/bouclier sur le point d'entrée HA (`ha-proxy`) : la
> vérification prouve que le service répond même pendant une bascule.

## Démo du workshop
1. Lancer une app démo (`demo-apps/paiement` ou `demo-apps/vitrine`).
2. `docker compose -f module/docker-compose.module.yml up -d` avec `PROTECTED_UPSTREAM` vers l'app.
3. Montrer : le cockpit (KPI live), envoyer du trafic + une attaque → WAF bloque, le détecteur
   voit l'anomalie, l'orchestrateur remédie, la bascule HA ; poser une question à l'assistant RAG.

> Données et attaques fictives, usage pédagogique / labo uniquement.
