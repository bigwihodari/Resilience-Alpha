# Procédures d'exploitation — Resilience Guard

## WAF : requêtes bloquées (403)

Le WAF de la passerelle inspecte le chemin, les paramètres de query et le corps de
chaque requête. Si une signature correspond (injection SQL, XSS…), la requête est
bloquée en **403** et n'atteint jamais l'application protégée. Le compteur
`waf_blocked_total{rule}` est incrémenté.

Règles couvertes : `sqli_or_and`, `sqli_union`, `sqli_tautology`, `sqli_drop`,
`sqli_insert`, `sql_comment`, `xss_script`.

**Que faire ?** Rien d'urgent : l'attaque est déjà bloquée en amont. Vérifier dans
Grafana / le cockpit quelle règle se déclenche et depuis quelle source. L'orchestrateur
marque l'état sécurité « Injection contenue » tant que les tentatives durent.

## Détection d'anomalie (ML)

Le détecteur apprend d'abord la « vie normale » (phase d'apprentissage, ~30 échantillons).
Une fois entraîné, il calcule un score d'anomalie (0-100). Au-delà du seuil, `anomaly_flag`
passe à 1. Un pic de trafic, d'erreurs 5xx ou de blocages WAF fait monter le score.

**Que faire ?** L'orchestrateur réagit tout seul (voir ci-dessous). Si le trafic normal
a durablement changé, forcer un ré-apprentissage via `POST /retrain` sur le détecteur.

## Remédiation autonome (anti-DoS)

Quand le ML confirme une anomalie (plusieurs cycles consécutifs), l'orchestrateur :
1. active le **bouclier de load-shedding** sur la passerelle (`POST /admin/protect`
   `{enabled:true, rate:N}`), ce qui déleste les requêtes au-delà d'un débit (429) ;
2. exécute une **transaction canari** (`GET /health` de la passerelle) pour prouver que
   le service répond ;
3. lève le bouclier automatiquement après plusieurs cycles redevenus normaux.

## Bouclier manuel

Pour activer / désactiver le bouclier à la main (test, démo) :

```
curl -X POST http://localhost:8080/admin/protect \
  -H "X-Admin-Token: <ADMIN_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"enabled": true, "rate": 8}'
```

Mettre `enabled:false` pour le désactiver. Le token est celui de `ADMIN_TOKEN` (.env).

## Haute disponibilité

Le module prévoit une passerelle + application de **secours** (itération HA). En nominal,
une seule passerelle sert le trafic ; la bascule vers le secours se fait au niveau du
reverse-proxy en cas de panne du principal.

## Installation devant une application

Pointer `PROTECTED_UPSTREAM` vers l'URL de l'application (dockerisée : `http://mon-app:8000` ;
non dockerisée : `http://host.docker.internal:3000`), puis lancer l'overlay
`docker-compose.module.yml`. L'application est alors servie via la passerelle (port 8080),
protégée et supervisée, sans aucune modification de son code.
