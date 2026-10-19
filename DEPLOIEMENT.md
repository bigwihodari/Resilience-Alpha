# 🚀 Déployer Resilience-Alpha sur une nouvelle machine

Guide pas-à-pas pour lancer le projet après avoir récupéré le dépôt GitHub.
Aucune compétence dev requise : tout est conteneurisé, il n'y a **rien à installer**
à part Docker.

---

## 1. Prérequis (à installer une seule fois)

| Outil | Pourquoi | Lien |
|---|---|---|
| **Docker Desktop** (avec WSL2) | fait tourner toute la plateforme | https://www.docker.com/products/docker-desktop/ |
| **Git** | récupérer le code | https://git-scm.com/downloads |

> 💡 **Docker Desktop doit être lancé** (icône baleine en bas à droite, « Engine running »)
> avant de démarrer le projet. Au premier lancement, laisse-le finir de démarrer (~1 min).

Config conseillée (PC Hôte) : Windows 10/11, 16 Go de RAM, virtualisation activée.

---

## 2. Récupérer le projet

Ouvre un terminal (PowerShell ou Git Bash) et place-toi où tu veux ranger le projet :

```bash
git clone https://github.com/bigwihodari/Resilience-Alpha.git
cd Resilience-Alpha
```

Pour **mettre à jour** plus tard (récupérer les dernières versions de l'équipe
et redémarrer proprement, même si la stack tourne déjà) — une seule commande :

- **Windows** : `.\update.ps1`
- **Git Bash / Linux / Mac** : `./update.sh`

> Le script fait `git pull` puis `docker compose up -d --build --remove-orphans` :
> il reconstruit et redémarre uniquement les conteneurs modifiés, sans tout casser.

---

## 3. Lancer (une seule commande)

### Option A — script tout-en-un (recommandé)

- **Windows (PowerShell)** :
  ```powershell
  .\start.ps1
  ```
- **Git Bash / Linux / Mac** :
  ```bash
  ./start.sh
  ```

Le script crée le fichier `.env` si besoin, puis construit et démarre tout.

### Option B — commande manuelle

```bash
cp .env.example .env     # (PowerShell : copy .env.example .env)
docker compose up -d --build
```

⏳ Le **premier** lancement télécharge et construit les images (quelques minutes).
Les fois suivantes, c'est quasi instantané.

---

## 4. Utiliser la plateforme (poste HÔTE)

👉 **Un seul point d'entrée : l'application de paiement.** Une fois connecté, le
**Hub** (page d'accueil) donne accès à **tout** sans avoir à chercher les URLs :
paiement, cockpit, Grafana, Prometheus, logs et documentation API.

| Interface | Adresse | Identifiants démo |
|---|---|---|
| **Application de paiement + Hub** | http://localhost:8080 | `alice` / `password123` |
| Cockpit de résilience | http://localhost:8080/cockpit | — |
| API (doc interactive) | http://localhost:8000/docs | — |
| Grafana (dashboards) | http://localhost:3000 | `admin` / `admin` |
| Prometheus (métriques) | http://localhost:9090/targets | — |
| Logs (Loki via Grafana) | http://localhost:3000/explore | — |

> Les ports sont modifiables dans `.env` (`FRONTEND_PORT`, `API_PORT`,
> `GRAFANA_PORT`, `PROMETHEUS_PORT`…) en cas de conflit. Le script `start.ps1`
> affiche les liens exacts à chaque lancement.

Tu dois voir la page de connexion, pouvoir te connecter et faire un paiement test.

> ℹ️ **Modèle à deux applications** : le **poste Hôte** fait tourner la plateforme
> (ci-dessus). Le **poste Attaquant** lance les attaques depuis sa **propre
> application unique** (console + indicateurs) — voir **section 7**.

---

## 5. Vérifier que tout marche (optionnel)

```bash
docker compose ps        # tous les services doivent être "Up" / "healthy"
curl http://localhost:8000/health
curl http://localhost:8001/health
```

---

## 6. Arrêter

```bash
docker compose down      # arrête tout (garde les données)
docker compose down -v   # arrête ET efface la base de données
```

---

## 7. Poste ATTAQUANT — son application (PC distinct)

L'attaque se lance depuis une **application unique dédiée**, à exécuter sur un
**second ordinateur** (le PC Attaquant), distinct du PC Hôte. Même dépôt, dossier
`attacker/`.

### a. Récupérer le projet (sur le PC Attaquant)

```bash
git clone https://github.com/bigwihodari/Resilience-Alpha.git
cd Resilience-Alpha/attacker
```

### b. Indiquer la cible (le PC Hôte)

```bash
cp .env.example .env     # (PowerShell : copy .env.example .env)
```

Puis éditer `.env` :

| Variable | Test local (même PC) | En labo (PC Hôte distant) |
|---|---|---|
| `TARGET_URL` | `http://host.docker.internal:8080` | `http://192.168.137.1:8080` |
| `TARGET_HOST` | `localhost` | `192.168.137.1` |

> `192.168.137.1` = l'adresse du PC Hôte sur le point d'accès Wi-Fi `RESILIENCE-G<n>`.

### c. Lancer

- **Windows** : `.\start.ps1`
- **Git Bash / Linux / Mac** : `./start.sh`

### d. Utiliser

La **console attaquant** (tout-en-un) : **http://localhost:8090**

On y trouve, sans rien chercher ailleurs :
- le lancement des attaques (**Saturation / DoS** et **Injection SQL**), avec intensité et durée ;
- les **indicateurs côté attaquant** en direct : requêtes envoyées/s, total, erreurs reçues, latence de la cible, graphe temps réel ;
- des **liens vers la supervision de la cible** (cockpit, app paiement, Grafana).

### e. Mettre à jour / arrêter

```bash
git pull && docker compose up -d --build   # mise à jour
docker compose down                        # arrêter
```

> ⚠️ Les attaques sont **strictement limitées** à la cible configurée et au labo
> de l'équipe. Jamais vers le réseau du campus, un autre groupe ou Internet.

---

## 8. Montage haute disponibilité (5 PC)

Topologie complète : 2 serveurs (principal + secours), 2 clients, 1 attaquant.

| PC | Rôle | Lancement |
|---|---|---|
| **HOST-PRINCIPAL** (192.168.137.1) | Serveur actif + cockpit | `./start.ps1` (ROLE=primary par défaut) |
| **HOST-BACKUP** (192.168.137.2) | Serveur de secours | compose complet avec `ROLE=backup` + `PEER_API_URL=http://192.168.137.1:8000` |
| **CLIENT-A / CLIENT-B** | App client | `cd client` puis `./start.ps1` |
| **ATTAQUANT** | Offensive | `cd attacker` puis `./start.ps1` |

### Serveur de secours (HOST-BACKUP, 2e PC)
Dans un `.env` à la racine du projet, régler puis lancer la stack complète :
```
ROLE=backup
PEER_API_URL=http://192.168.137.1:8000
JWT_SECRET=...        # IDENTIQUE au principal (tokens valides des deux côtés)
REPL_TOKEN=...        # IDENTIQUE au principal
```
Le backup réplique en continu les comptes et les clés d'idempotence du principal.

### Postes clients (`client/.env`)
```
HOST_PRIMARY=192.168.137.1    HOST_PRIMARY_API_PORT=8000   HOST_PRIMARY_AUTH_PORT=8001
HOST_BACKUP=192.168.137.2     HOST_BACKUP_API_PORT=8000    HOST_BACKUP_AUTH_PORT=8001
```
Connexion : `alice` sur CLIENT-A, `bob` sur CLIENT-B (ils se paient en direct).

### Comment ça bascule
Chaque app client vise le principal ; s'il tombe, **nginx route automatiquement vers
le backup** (qui a répliqué comptes + clés). Une transaction en cours est **reprise
sans double débit** grâce à la clé d'idempotence. Le backup se **promeut** autoritaire
après quelques secondes d'absence du principal.

### Test local (une seule machine)
```bash
docker compose -f docker-compose.backup.yml up -d --build   # backup en 8010/8011
cd client && cp .env.example .env && ./start.sh             # .env : backup 8010/8011
./scripts/recette-ha.sh                                      # recette de bascule
```

---

## 9. En cas de souci

| Problème | Solution |
|---|---|
| `error during connect ... docker_engine` | Docker Desktop n'est pas démarré → lance-le et attends « Engine running ». |
| Un port est déjà utilisé (8080/8000/8001/3000…) | ouvre `.env` et change le port concerné (`FRONTEND_PORT`, `API_PORT`, `GRAFANA_PORT`…), puis relance `./update.ps1`. cAdvisor n'expose plus de port (plus de conflit). |
| La page ne charge pas tout de suite | attends 15-20 s que les conteneurs finissent de démarrer, puis rafraîchis. |
| Repartir de zéro | `docker compose down -v` puis `docker compose up -d --build`. |

---

> ⚠️ Projet pédagogique : environnement, données et attaques **fictifs**, limités au
> labo de l'équipe. Ne jamais exposer la base de données ou les secrets sur le réseau.
