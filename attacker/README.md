# ⚔️ Console Attaquant — Resilience-Alpha

Application **unique** du poste Attaquant : une console web qui lance les attaques
contrôlées et affiche tous les indicateurs **côté attaquant**, plus les liens de
supervision de la cible. Tout au même endroit.

> ⚠️ Strictement limité au labo de l'équipe et à la cible configurée.
> Environnement et données fictifs.

## Lancer

```bash
cp .env.example .env     # puis adapter TARGET_URL / TARGET_HOST
./start.sh               # ou .\start.ps1 (PowerShell)
```

Console : http://localhost:8090

## Configurer la cible (`.env`)

| Variable | Exemple local | Exemple labo (PC distinct) |
|---|---|---|
| `TARGET_URL` | `http://host.docker.internal:8080` | `http://192.168.137.1:8080` |
| `TARGET_HOST` | `localhost` | `192.168.137.1` |

## Attaques disponibles

- **Saturation (DoS)** : flood de `/auth/login` (la vérification de mot de passe
  est coûteuse → CPU et latence de la cible montent, le service devient indisponible).
- **Injection SQL** : envoi de charges utiles SQL sur `/auth/login` (visibles dans
  les logs / le WAF de la cible).

Réglages : type, **intensité** (nb de workers), **durée** (auto-stop).

## Indicateurs affichés

Requêtes envoyées/s, total envoyé, erreurs reçues (5xx = la cible flanche),
latence de la cible, codes de réponse, et un graphe temps réel.
