# Applications de démonstration — « on protège n'importe quoi »

Deux petites applications à placer **derrière** le module [Resilience Guard](../module/README.md).
Elles n'embarquent aucune sécurité : c'est la passerelle du module, posée devant, qui les
protège et les supervise — **sans toucher à leur code**.

| Démo | Ce que c'est | Port direct | Dossier |
|------|--------------|-------------|---------|
| **vitrine** | Site vitrine statique (« Ma Boutique ») — app **vierge** | `8090` | [`vitrine/`](vitrine/) |
| **paiement** | Petite app métier FastAPI (login + solde + paiement) | `8000` | [`paiement/`](paiement/) |

---

## 1 commande : lancer une démo, puis brancher le module

### Option A — démo vitrine (app vierge)

```bash
# 1) lancer l'app de démo (non protégée, en direct sur 8090)
cd demo-apps/vitrine
docker compose up -d --build

# 2) poser le module devant (depuis module/)
cd ../../module
cp .env.example .env            # PROTECTED_UPSTREAM pointe déjà sur http://host.docker.internal:8090
docker compose -f docker-compose.module.yml up -d --build
```

### Option B — démo paiement (app métier)

```bash
cd demo-apps/paiement
docker compose up -d --build     # app directe sur http://localhost:8000

cd ../../module
cp .env.example .env
# éditer .env : PROTECTED_UPSTREAM=http://host.docker.internal:8000
docker compose -f docker-compose.module.yml up -d --build
```

### Ce qu'on obtient

| URL | Rôle |
|-----|------|
| `http://localhost:8080` | l'application **servie via la passerelle** (protégée + mesurée) |
| `http://localhost:8088` | le **cockpit** Resilience Guard (santé, KPI, détection IA, remédiation, WAF, assistant) |
| `http://localhost:3000` | **Grafana** (observabilité détaillée) |
| `http://localhost:9090` | **Prometheus** |
| `http://localhost:8090` / `:8000` | l'app **en direct**, non protégée (pour comparer) |

> La passerelle joint l'app via `host.docker.internal` : les deux `docker compose` restent
> indépendants, aucun réseau partagé à configurer. Pour une app déjà dockerisée sur le même
> réseau, on peut aussi mettre `PROTECTED_UPSTREAM=http://<nom-du-service>:<port>`.

Arrêt : `docker compose -f docker-compose.module.yml down` (dans `module/`) puis
`docker compose down` (dans le dossier de la démo).

---

## Scénario de présentation (workshop)

1. **Trafic normal.** Ouvrir l'app protégée (`:8080`) et le cockpit (`:8088`). Cliquer /
   naviguer un peu (sur la démo paiement : se connecter en `alice / demo123`, faire un
   paiement). → Le cockpit montre le **débit**, la **latence p95**, les **services en ligne**.
   Laisser le détecteur ML terminer son apprentissage de la normale (badge « apprentissage… »
   → « comportement normal »).

2. **Attaque applicative (injection SQL).** Envoyer une requête malveillante à travers la
   passerelle :

   ```bash
   curl "http://localhost:8080/?q=' OR 1=1--"
   # -> HTTP 403 : requête bloquée par le WAF
   ```

   En rafale pour la démo :

   ```bash
   for i in $(seq 1 40); do curl -s -o /dev/null "http://localhost:8080/?q=' OR 1=1--"; done
   ```

   → Dans le cockpit : le compteur **« Requêtes bloquées (WAF) »** grimpe, le graphe WAF
   réagit, et l'**orchestrateur** passe en « Injection contenue » puis prouve par un
   **canari** que l'application, elle, n'a jamais reçu les requêtes malveillantes.

3. **Montée en charge / anomalie.** Générer un pic de trafic (beaucoup de requêtes d'un coup) :

   ```bash
   for i in $(seq 1 2000); do curl -s -o /dev/null "http://localhost:8080/" & done; wait
   ```

   → Le **détecteur ML** voit l'écart à la normale : le **score d'anomalie** monte, le drapeau
   passe au rouge. L'**orchestrateur** décide, active le **bouclier anti-DoS** sur la passerelle
   (load-shedding, les requêtes en excès sont délestées en 429), vérifie par un **canari**, puis
   lève le bouclier quand le trafic revient à la normale. Toute la **timeline** est visible dans
   le cockpit.

4. **Assistant RAG.** Dans le cockpit, poser une question à l'assistant, par ex.
   *« Que fait le module quand le WAF bloque une requête ? »* ou *« Comment fonctionne la
   remédiation anti-DoS ? »* → réponse générée en local (Ollama) à partir de la documentation
   du module, avec les sources citées.

> Toutes les données et attaques sont **fictives**, à usage **pédagogique / labo** uniquement.
