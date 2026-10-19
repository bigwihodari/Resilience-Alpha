# Gouvernance & transformation — synthèse

Documents (reliés à l'architecture et aux essais réels) :
- [Analyse de risques EBIOS RM](ebios-rm.md)
- [PCA / PRA](pca-pra.md)
- [Conformité NIS2 & DORA](nis2-dora.md)

## En une page (pour la direction)

**Enjeu.** Une plateforme de paiement perd de la valeur à chaque minute
d'indisponibilité et à toute atteinte à l'intégrité des données. L'objectif de
Resilience-Alpha est de **réduire le temps d'indisponibilité à presque zéro** par une
reprise **autonome**, et de **contenir les tentatives de compromission**.

**Ce que nous protégeons en priorité.** L'exécution des paiements et l'intégrité des
données de comptes (valeurs métier VM1 et VM3).

**Risques majeurs retenus et traitement.**
| Risque | Traitement | Risque résiduel |
|---|---|---|
| Déni de service → indisponibilité | Détection ML + bouclier auto + canari | Saturation réseau amont |
| Injection SQL → altération/fuite | WAF + contrôle d'intégrité | Contournement par obfuscation |
| Accès non autorisé | JWT + moindre privilège | — |

**Ce que coûte une panne.** Toute indisponibilité du paiement retarde les opérations
des partenaires et érode la confiance ; notre RTO mesuré (~15 s) limite cet impact.

**Arbitrages assumés.** Prototype mono-hôte (pas de HA), WAF à signatures (pas de WAF
réseau), notification réglementaire non implémentée — choix cohérents avec un sprint
de 4 jours, documentés comme risques résiduels.

**Recommandations prioritaires.** (1) Industrialiser la reprise (HA + WAF réseau) ;
(2) formaliser la notification d'incident NIS2/DORA à partir de la traçabilité
existante ; (3) planifier des tests de résilience réguliers.

**Éléments vérifiables.** RTO mesuré, taux de blocage WAF, score d'anomalie ML,
succès des transactions canari — tous observables dans le cockpit et Prometheus.
