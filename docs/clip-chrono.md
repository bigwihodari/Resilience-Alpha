# 🎬 Clip Chrono — scénario minuté (≤ 60 s, sans coupe)

Objectif (sujet) : une séquence **continue**, sans coupe masquant une action manuelle,
montrant **lancement de l'attaque → anomalie → réaction du système → service rétabli**.
Lisible à distance (titres/sous-titres conseillés).

## Préparation (avant de lancer l'enregistrement)
- Stack démarrée (`./start.ps1`), détecteur **entraîné** (cockpit : score à 0).
- Deux fenêtres visibles côte à côte :
  - **Gauche** : la **console attaquant** (http://localhost:8090).
  - **Droite** : le **cockpit** de l'hôte (http://localhost:8080/cockpit).
- Vérifier d'abord avec `./scripts/recette.sh` que tout est vert.

## Déroulé (60 s)
| Temps | À l'écran | Sous-titre suggéré |
|---|---|---|
| 0–8 s | Cockpit : tout vert, score 0, un paiement de test réussit | « État nominal : service de paiement opérationnel » |
| 8–15 s | Console attaquant : choisir **Saturation (DoS)**, cliquer **Lancer** | « Attaque lancée depuis le PC attaquant » |
| 15–25 s | Cockpit : débit/latence s'envolent, **score → 100**, « ANOMALIE DÉTECTÉE » | « Détection automatique par machine learning » |
| 25–38 s | Cockpit : timeline **Décision → Bouclier actif → Vérification**, canari **✓ OK** | « Remédiation autonome, sans intervention humaine » |
| 38–48 s | Cockpit : un **nouveau paiement réussit** malgré l'attaque | « Preuve : une transaction réussit après l'incident » |
| 48–58 s | Console attaquant : lancer **Injection SQL** → cockpit SOC « Injection contenue », intégrité ✓ | « Injection SQL bloquée par le WAF, données intègres » |
| 58–60 s | Plan large des deux écrans | « Cyber-résilience : détection, reprise et preuve » |

## Conseils de tournage
- **Une seule prise, sans coupe** (obligatoire). Répéter avant d'enregistrer.
- Lancer l'attaque réellement depuis la console (pas de simulation).
- Grossir le cockpit (zoom navigateur) pour la lisibilité à distance.
- Durée stricte : viser 55 s pour garder une marge.
- Fichier de rendu : `Workshop2026-M2-G<n>-VidChrono.mp4`.

## Variante haute disponibilité (démo bascule 5 PC)
Montre, en plus, la continuité de service quand le serveur tombe :
| Temps | À l'écran | Sous-titre |
|---|---|---|
| 0–10 s | CLIENT-A paie CLIENT-B (transfert en direct) | « Paiement entre clients via le serveur principal » |
| 10–20 s | L'attaquant fait tomber le principal ; le client affiche « serveur indisponible — reprise » | « Le serveur principal tombe » |
| 20–35 s | Le même paiement aboutit + un nouveau paiement passe | « Bascule automatique sur le backup, transaction reprise sans double débit » |
| 35–45 s | Cockpit du backup : service actif | « Service maintenu, reprise autonome » |
Script reproductible : `./scripts/recette-ha.sh`.

## Démonstration live (jury) — même logique en 3 min
1. (30 s) État nominal + un paiement.
2. (60 s) DoS depuis la console → détection ML → bouclier → canari OK.
3. (45 s) Injection SQL → WAF + contrôle d'intégrité.
4. (30 s) Retour à la normale + lecture du cockpit (score, timeline, SOC).
5. (15 s) Assistant RAG : poser une question sur l'incident.
