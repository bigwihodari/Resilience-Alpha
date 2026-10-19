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

Pour **mettre à jour** plus tard (récupérer les dernières versions de l'équipe) :

```bash
git pull
```

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

## 4. Utiliser la plateforme

| Interface | Adresse | Identifiants démo |
|---|---|---|
| **Paiement (frontend)** | http://localhost:8080 | `alice` / `password123` |
| API (doc interactive) | http://localhost:8000/docs | — |
| Auth | http://localhost:8001 | — |

Tu dois voir la page de connexion, pouvoir te connecter et faire un paiement test.

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

## 7. En cas de souci

| Problème | Solution |
|---|---|
| `error during connect ... docker_engine` | Docker Desktop n'est pas démarré → lance-le et attends « Engine running ». |
| Un port est déjà utilisé (8080/8000/8001) | ferme l'appli qui l'utilise, ou change le port dans `docker-compose.yml`. |
| La page ne charge pas tout de suite | attends 15-20 s que les conteneurs finissent de démarrer, puis rafraîchis. |
| Repartir de zéro | `docker compose down -v` puis `docker compose up -d --build`. |

---

> ⚠️ Projet pédagogique : environnement, données et attaques **fictifs**, limités au
> labo de l'équipe. Ne jamais exposer la base de données ou les secrets sur le réseau.
