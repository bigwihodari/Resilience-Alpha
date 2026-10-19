# 🔐 Posture de sécurité — Resilience-Alpha

Synthèse des dispositifs défensifs du prototype (pilier Cybersécurité).

## 1. WAF applicatif (filtrage des entrées)
Inspection des entrées dans `auth` et `api` (signatures type OWASP : SQLi, XSS).
Toute requête correspondant à une signature est **bloquée (403)**, journalisée
(`[WAF] BLOCK …` → Loki) et comptée (`waf_blocked_total{rule}` → Prometheus).
→ L'injection SQL lancée depuis le poste attaquant est bloquée en amont.

## 2. SIEM / fonction SOC
La fonction SOC est **intégrée à la supervision** (autorisé par le sujet) :
- **Loki** centralise les journaux (dont les blocages WAF) ;
- **Prometheus** expose les signaux de sécurité (`waf_blocked_total`, taux de 4xx,
  `anomaly_flag`) ;
- le **cockpit** présente une vue SOC (requêtes bloquées, état sécurité, intégrité) ;
- l'**orchestrateur** corrèle ces signaux et déclenche la réponse.

## 3. Deux incidents, deux réponses (ne pas confondre)
- **DoS (disponibilité)** : détecté par le ML (débit/erreurs) → bouclier anti-DoS
  (load-shedding) + transaction canari → service rétabli.
- **Injection SQL (compromission)** : bloquée par le WAF → **contrôle d'intégrité
  des données** (`/admin/integrity`) → confirmation qu'aucune donnée n'est altérée.
  (Réponse différente d'une simple restauration de disponibilité.)

## 4. Moindre privilège (accès maîtrisés)
- L'orchestrateur n'a **pas** d'accès god-mode aux conteneurs : il agit via une API
  d'administration **scoped** (`/admin/protect`, `/admin/integrity`), protégée par
  un `ADMIN_TOKEN` dédié. Un seul type d'action possible.
- Les clients internes de confiance (canari, trafic) utilisent un `INTERNAL_TOKEN`
  distinct (exemption de bouclier uniquement).

## 5. Isolation réseau
- La base de données n'est **pas** publiée sur le réseau.
- cAdvisor n'expose pas de port hôte (scrape interne).
- Entrées publiées avec discernement (front/API/observabilité uniquement).

## 6. Durcissement
- `no-new-privileges:true` sur les services applicatifs (pas d'élévation de
  privilèges in-container).
- Images légères (`-slim` / `-alpine`), dépendances épinglées.

## 7. Gestion des secrets — SOPS + age
Aucun secret en clair dans le dépôt (`.env` est ignoré ; `.env.example` ne contient
que des valeurs de dev). En conditions réelles, les secrets sont **chiffrés avec
SOPS + age** :

```bash
# 1. installer sops + age   (Windows : winget install FiloSottile.age ; Mozilla.sops)
# 2. générer une clé age
age-keygen -o age.key            # garder la clé PRIVÉE hors dépôt
#    -> copier la clé PUBLIQUE (age1...) dans .sops.yaml
# 3. créer les secrets puis les chiffrer
cp secrets/secrets.example.env secrets/secrets.sops.env   # mettre les vraies valeurs
sops -e -i secrets/secrets.sops.env                        # chiffre en place (versionnable)
# 4. au déploiement : déchiffrer vers .env
export SOPS_AGE_KEY_FILE=age.key
./scripts/secrets-decrypt.sh
```

Seuls `secrets/secrets.example.env` et le fichier **chiffré** `*.sops.env` sont
versionnés ; la clé privée et le `.env` déchiffré ne le sont jamais.
