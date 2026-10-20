# RESILIENCE-ALPHA — Jeu idle multijoueur « éco vs cyber »

Plan validé le 2026-10-20. But : premier à **1 000 000 €** gagne (client ou attaquant).
On garde TOUTE la stack (Docker, FastAPI, React, Postgres, Prometheus/Grafana/Loki,
détecteur IF, orchestrateur, WAF, JWT, HA/réplication, Ollama RAG, WebSockets).
Backup conservé (techno gardée) mais mis de côté du game-loop.

## Phases
- [ ] **P0 — Noyau éco** : table `livrets` (N par client), production idle généralisée
      (+ gains hors-ligne), fortune (courant + livrets), leaderboard live, victoire 1 M.
- [ ] **P1 — Shop & upgrades** : coûts exponentiels `base*r^n` ; achat de livrets/taux/
      capacité/sécurité ; refonte dashboard client.
- [ ] **P2 — Mailbox / enchères / quiz** : boîte mail, enchères officielles (banque),
      quiz banquier (1re bonne réponse créditée) + managers côté banque.
- [ ] **P2.5 — Chat** : chat global + **chats privés** (créer un salon, ajouter les
      personnes voulues) en temps réel (WebSocket) pour tout le monde (clients,
      attaquants, banquier). Tables `chat_rooms` / `chat_members` / `chat_messages`.
- [ ] **P2.6 — Banquier insider (vend de l'info)** : le banquier peut **vendre de
      l'intel** (recon sur un client : solde, présence de livret…) à un attaquant
      contre un **prix** ; l'attaquant paie (butin) et reçoit l'info → hack facilité.
      (relie banquier P2 + attaquant P3/P3.5 ; traçable, l'IA peut le flaguer).
- [ ] **P2.7 — Mini-jeu Dino** : jeu type dino Chrome côté client ; récolte de pièces
      → argent crédité au compte (serveur valide, anti-triche, plafonds) ; **bonus
      x5/x10/x100** pendant la run. **Hack attaquant** : analyser une session de jeu
      active et détourner le compte destinataire du gain (requête complexe), protégé
      par l'IA (difficile, suspicion).
- [ ] **P3 — Attaquant v2** : boîte à outils de requêtes (recon/vol), cibles clients &
      attaquants (PvP), scoreboard butin (déjà v1), bibliothèque/doc.
- [ ] **P3.5 — Éco du vol (risque/récompense)** :
  - [ ] Vol de la **banque (trafficbot)** : très rentable mais très sécurisé ; difficulté
        croît avec le montant visé ; **cramé = perte TOTALE du butin + cooldown 5 min**.
  - [ ] Vol de **clients** : plus facile, **difficulté exponentielle** selon fréquence ET
        montant visé ; **cramé = l'attaquant perd ~80 % du montant**, et le montant est
        **remboursé au client** (claw-back existant).
  - [ ] **Shop hacker** : upgrades de furtivité (réduit montée de suspicion), rotation
        d'IP/proxy (réduit proba de blocage), outils (plafond/facilité de vol), décodeurs
        d'intel (recon plus rapide) — coûts exponentiels, payés avec le butin.
- [ ] **P4 — Détection par IP** : suspicion `s∈[0,1]` par IP/acteur (monte avec les
      signaux, décroît avec le temps) ; **blocage probabiliste** `p=f(s)` (pas 100 %) ;
      **isolation** (on bloque le suspect, pas les deux) ; cooldown ; branché détecteur/
      orchestrateur ; HA conservée.
- [ ] **P5 — Phishing** : faux mails + fausses pages d'enchère ; si un client clique et
      enchérit → vol à la clôture ; détection de fraude.
- [ ] **P6 — Refonte UI/design** : client (dashboard idle animé, shop, mailbox, leaderboard),
      attaquant (terminal hacker, heat/suspicion, phishing, lib), host (cockpit + managers).
- [ ] **P7 — Équilibrage + fin de partie** : courbes coûts/taux/plafonds/suspicion ; écran
      de victoire ; docs (guides, dossier, deck + PDF/PPTX) ; rebuild/test MSI.

## Règles d'exécution
- Un seul éditeur de `services/api/app/main.py` à la fois (moi) → commits séquentiels sur `main`.
- Sessions dédiées pour les fronts indépendants (client / host / attaquant) une fois les
  endpoints backend prêts (P6).
- Migrations idempotentes ; builds front validés (`npm run build`) ; `.ps1` ASCII ;
  chart.umd vendored ; test sur MSI par SSH (pré-pull images de base).

## Review
_(à remplir en fin de phase)_
