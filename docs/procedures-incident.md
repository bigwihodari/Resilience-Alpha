# Procédures d'incident — Resilience-Alpha (runbook opérateur)

## Vue d'ensemble
La plateforme détecte et corrige seule les incidents (reprise autonome). L'opérateur
observe et comprend ; il n'a normalement pas à intervenir. En cas de doute, consulter
le cockpit (http://localhost:8080/cockpit) : état des systèmes, KPIs, score d'anomalie,
timeline de remédiation et vue SOC.

## Incident 1 — Déni de service (DoS) : perte de disponibilité
Signes : débit d'authentification très élevé, latence qui grimpe, pic d'erreurs 4xx,
score d'anomalie ML proche de 100.
Réponse automatique :
1. Le détecteur ML signale l'anomalie.
2. L'orchestrateur active le « bouclier » anti-DoS sur le service d'authentification
   (load-shedding : les requêtes excédentaires non internes reçoivent 429, sans calcul coûteux).
3. Une transaction canari (login + paiement) vérifie que le service est de nouveau utilisable.
4. Quand l'attaque cesse, le bouclier est désactivé automatiquement.
Que fait l'opérateur : rien. Il vérifie dans le cockpit que l'état passe à « Service rétabli »
et que le canari est OK.

## Incident 2 — Injection SQL : tentative de compromission
Signes : requêtes bloquées par le WAF (compteur qui monte), état sécurité « Injection contenue ».
Réponse automatique :
1. Le WAF applicatif bloque les charges utiles malveillantes (403) et les journalise.
2. L'orchestrateur lance un contrôle d'intégrité des données (comptes attendus, pas
   d'utilisateur suspect, soldes cohérents).
3. Si l'intégrité est confirmée : aucune donnée altérée, incident contenu.
   Si une altération était détectée : restauration depuis une sauvegarde saine.
Important : restaurer la disponibilité (DoS) et corriger une compromission (injection) sont
deux réponses DIFFÉRENTES.

## Lire le cockpit
- État des systèmes : vert = en ligne, rouge = hors ligne.
- Score d'anomalie (0–100) : au-delà du seuil appris, une anomalie est signalée.
- Remédiation autonome : étapes Surveillance → Action → Vérification → Rétabli + timeline.
- Sécurité (SOC) : requêtes bloquées par le WAF, état sécurité, intégrité des données.

## Qui fait quoi
- Détection : service `detector` (modèle Isolation Forest + distance à la normale).
- Décision et action : service `orchestrator` (droits limités, API d'admin dédiée).
- L'assistant (ce module) aide à COMPRENDRE ; il ne peut pas agir sur le système.

## Démarrer / arrêter / mettre à jour
- Démarrer : `./start.ps1` (Windows) ou `./start.sh`.
- Mettre à jour : `./update.ps1` ou `./update.sh`.
- Arrêter : `docker compose down`.
