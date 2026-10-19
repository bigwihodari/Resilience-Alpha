# Conformité — NIS2 & DORA

> Lecture appliquée à une entité financière fictive. On distingue ce que le
> prototype **démontre réellement** de ce qu'un prototype de 4 jours **ne peut pas**
> démontrer.

## 1. NIS2 (directive UE sur la cybersécurité)

| Exigence NIS2 | Démontré par le prototype | À compléter en réel |
|---|---|---|
| Gestion des risques (analyse, mesures) | EBIOS RM relié à l'archi + mesures techniques | Processus récurrent, revue de direction |
| Détection & gestion d'incidents | Détection ML + réponse automatique + journalisation | Procédures humaines, astreinte |
| Continuité d'activité | PCA/PRA + reprise autonome vérifiée | HA, tests réguliers, sauvegardes externalisées |
| Notification d'incidents (24 h / 72 h) | Traçabilité (Loki) comme base d'un rapport | Canal de notification à l'autorité, délais |
| Sécurité de la chaîne d'approvisionnement | Dépendances épinglées, images officielles | Évaluation des fournisseurs, SBOM |
| Gouvernance & responsabilité | Rôles définis (PCA/PRA) | Engagement de la direction, formation |

## 2. DORA (résilience opérationnelle numérique — secteur financier)

| Pilier DORA | Démontré par le prototype | À compléter en réel |
|---|---|---|
| Gestion du risque TIC | Mesures techniques + analyse de risques | Cadre de gouvernance TIC formalisé |
| Gestion des incidents TIC | Détection, réponse, journalisation | Classification, reporting réglementaire |
| Tests de résilience | Attaques contrôlées + chaos (DoS, injection) | TLPT (tests d'intrusion avancés) encadrés |
| Risque lié aux tiers TIC | — | Registre des prestataires, clauses contractuelles |
| Partage d'informations | — | Participation aux dispositifs sectoriels |

## 3. Ce que le prototype prouve concrètement
- Une chaîne **détection → réponse → vérification** fonctionnelle et observable.
- Deux types d'incidents avec **réponses différenciées** (disponibilité vs compromission).
- Une **traçabilité** exploitable (métriques + logs) pour l'investigation.

## 4. Limites assumées (non démontrables en 4 jours)
- Reporting réglementaire et notification aux autorités.
- Gouvernance organisationnelle, registre des tiers, SBOM.
- Haute disponibilité et tests de résilience à grande échelle (TLPT).

## 5. Recommandations à la direction
1. **Prioriser la disponibilité du paiement** : la reprise autonome réduit fortement
   le temps d'indisponibilité ; l'industrialiser (HA + WAF réseau) est le meilleur
   rapport valeur/effort.
2. **Formaliser la notification d'incident** (NIS2/DORA) : s'appuyer sur la
   traçabilité déjà en place pour produire les rapports dans les délais.
3. **Mettre en place des tests de résilience réguliers** (chaos engineering) :
   le dispositif d'attaque contrôlée existe déjà, l'étendre et le planifier.
4. **Gérer le risque tiers** : registre des dépendances/fournisseurs TIC (DORA).
5. **Sur quels éléments vérifiables fonder la décision** : RTO mesuré (~15 s),
   taux de blocage WAF, score d'anomalie, succès des transactions canari — tous
   observables dans le cockpit et Prometheus.
