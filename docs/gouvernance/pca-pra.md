# PCA / PRA — Plan de continuité et de reprise

> Adapté au démonstrateur Resilience-Alpha. Le PCA vise à maintenir le service,
> le PRA à le rétablir. Ici, la reprise est **autonome** (zero-touch).

## 1. Services critiques et objectifs
| Service | Criticité | RTO cible | RPO cible |
|---|---|---|---|
| Paiement (`api`) | Vitale | Reprise auto < 30 s après détection | 0 (base persistante) |
| Authentification (`auth`) | Vitale | < 30 s | 0 |
| Base de données (`db`) | Vitale | Restauration depuis snapshot | Dernier snapshot sain |
| Supervision / cockpit | Importante | Best effort | n/a |

**Mesure réelle** : sur l'incident DoS, la chaîne détection → décision → bouclier →
vérification canari s'exécute en **~15 s**, soit en deçà du RTO visé.

## 2. Scénarios couverts et réponses
| Scénario | Type d'atteinte | Réponse (automatique) | Preuve de reprise |
|---|---|---|---|
| DoS (SO1) | Disponibilité | Bouclier anti-DoS (load-shedding) + relâche auto | Transaction canari réussie (~220 ms) |
| Injection SQL (SO2) | Intégrité / confidentialité | Blocage WAF + contrôle d'intégrité (+ restauration snapshot si altération) | Intégrité confirmée (comptes, soldes) |

> **Distinction clé** : restaurer la **disponibilité** (DoS) ≠ corriger une
> **compromission** (injection). Les deux playbooks sont séparés.

## 3. Mécanisme de reprise (zero-touch)
1. Collecte continue (Prometheus/Loki).
2. Détection (service `detector`, ML).
3. Décision + action (service `orchestrator`, droits limités).
4. **Vérification** par transaction canari de bout en bout (login + paiement).
5. Retour automatique à l'état nominal quand la menace cesse.

## 4. Responsabilités
| Acteur | Rôle |
|---|---|
| Automate de remédiation (`orchestrator`) | Détecte, décide, agit, vérifie |
| Opérateur | Supervise le cockpit, décide d'une escalade éventuelle |
| Équipe d'ingénierie | Maintient la plateforme, met à jour les règles/modèle |
| Assistant RAG | Aide l'opérateur à comprendre (sans agir) |

## 5. Sauvegarde & restauration
- Données dans un volume PostgreSQL persistant (survit aux redémarrages).
- Compromission : restauration depuis un snapshot sain (RPO = dernier snapshot).
- Modèle ML persisté (volume) : pas de ré-apprentissage après redémarrage.

## 6. Risques subsistant après reprise
- Persistance de l'attaquant (le bouclier atténue, ne supprime pas la source).
- Saturation réseau en amont de l'application (hors périmètre applicatif).
- Pas de bascule multi-site (mono-hôte) : panne matérielle de l'hôte non couverte.
- Contournement WAF / angle mort du ML : détection imparfaite.

## 7. Plan d'amélioration (industrialisation)
- Haute disponibilité (réplication DB, plusieurs nœuds).
- Blocage par IP / réputation au niveau d'un vrai WAF réseau (ModSecurity/Coraza).
- Sauvegardes planifiées + tests de restauration réguliers.
- Enrichissement du modèle ML (plus de features, ré-entraînement périodique).
