# Analyse de risques — EBIOS Risk Manager

> Analyse appliquée au démonstrateur Resilience-Alpha (plateforme de paiement
> fictive). Volontairement reliée à l'architecture réelle et aux essais menés.

## Atelier 1 — Cadrage et socle de sécurité

### Valeurs métier
| # | Valeur métier | Description | Besoin principal |
|---|---|---|---|
| VM1 | Exécution des paiements | Initier et traiter une transaction | Disponibilité, intégrité |
| VM2 | Authentification | Vérifier l'identité des utilisateurs | Disponibilité, confidentialité |
| VM3 | Données de comptes & transactions | Soldes, historique | Intégrité, confidentialité |
| VM4 | Supervision & reprise | Observer et rétablir le service | Disponibilité |

### Biens supports
`api` (traitement), `auth` (JWT), `db` PostgreSQL (données), `frontend`,
`orchestrator` (remédiation), `detector` (ML), stack Prometheus/Grafana/Loki,
hôte Docker + réseau Wi-Fi du groupe.

### Événements redoutés
| # | Événement redouté | Impact | Gravité |
|---|---|---|---|
| ER1 | Indisponibilité du service de paiement | Perte d'activité, perte de confiance | Critique (4) |
| ER2 | Altération des données (soldes, comptes) | Fraude, incohérence comptable | Critique (4) |
| ER3 | Exfiltration de données de comptes | Non-conformité, atteinte vie privée | Grave (3) |
| ER4 | Usurpation d'identité / accès non autorisé | Transactions frauduleuses | Grave (3) |

### Socle de sécurité
Conteneurisation isolée, DB non exposée, JWT, secrets hors dépôt, journalisation
centralisée. Écarts connus : prototype mono-hôte, pas de HA.

## Atelier 2 — Sources de risque (SR) et objectifs visés (OV)
| SR | Objectif visé |
|---|---|
| Attaquant opportuniste | Nuire à la disponibilité (déni de service) |
| Fraudeur | Voler / altérer des données (injection) |
| Script-kiddie | Exploiter une faille connue, défigurer |

## Atelier 3 — Scénarios stratégiques
- SS1 : un attaquant sature le service d'authentification → ER1 (indisponibilité).
- SS2 : un fraudeur injecte du SQL via un champ exposé → ER2/ER3 (altération/exfiltration).
- SS3 : un attaquant tente de contourner l'authentification → ER4.

## Atelier 4 — Scénarios opérationnels (testés sur le démonstrateur)
### SO1 — Déni de service (réalisé)
Flood de `/auth/login` (vérification bcrypt coûteuse) depuis le PC Attaquant.
**Mesuré** : latence auth ×5 (95 ms → ~490 ms), débit auth ×30 (~1 → ~35 req/s),
score d'anomalie ML 0 → 100.
### SO2 — Injection SQL (réalisé)
Charges utiles SQL (`' OR '1'='1`, `UNION SELECT`, `DROP TABLE…`) dans `/auth/login`.
**Mesuré** : bloquées par le WAF (403), ~748 requêtes bloquées comptabilisées,
état sécurité « Injection contenue », contrôle d'intégrité OK.

## Atelier 5 — Traitement du risque
| Mesure (implémentée) | Risque couvert | Type |
|---|---|---|
| Détection ML (Isolation Forest + distance) | SO1 | Détection |
| Bouclier anti-DoS (load-shedding) + canari | SO1 / ER1 | Réduction / reprise |
| WAF applicatif (signatures OWASP) | SO2 / ER2-ER3 | Réduction |
| Contrôle d'intégrité des données | SO2 / ER2 | Réduction / vérification |
| Moindre privilège orchestrateur (token scoped) | ER4 | Réduction |
| Durcissement (no-new-privileges), DB non exposée | tous | Réduction |
| Secrets chiffrés (SOPS + age) | ER3 | Réduction |
| Observabilité (Prometheus/Grafana/Loki) | tous | Détection / traçabilité |

### Matrice de risque (après traitement)
| Scénario | Gravité | Vraisemblance résiduelle | Niveau résiduel |
|---|---|---|---|
| SO1 DoS | Critique | Faible (détecté + atténué auto) | Moyen |
| SO2 Injection | Critique | Faible (bloqué par WAF) | Faible-Moyen |
| Usurpation (ER4) | Grave | Faible | Faible |

### Risques résiduels (assumés)
- WAF à signatures : contournement possible (obfuscation, encodage).
- ML : faux positifs/négatifs ; attaques « low-and-slow » moins visibles ; dépend de
  la qualité de la baseline.
- Bouclier DoS : protège l'application, pas une saturation réseau en amont.
- Prototype mono-hôte : pas de haute disponibilité ni de reprise multi-site.
- Dépend de la bonne gestion de la clé age (secrets).
