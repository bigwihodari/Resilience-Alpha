# Ansible : déploiement, vérification et reprise

Exécution locale (`connection: local`) sur le PC Hôte. Aucune collection externe :
uniquement `command`, `shell`, `uri` et `debug`. Variables de démo dans `group_vars/all.yml`.

## Ansible vs orchestrateur

| | Orchestrateur (Python, dans le module) | Ansible (ce dossier) |
|---|---|---|
| Quand | Temps réel, en continu | À la demande |
| Rôle | Remédiation autonome : bouclier anti-DoS, canari, état « menace contenue » | Déploiement reproductible, vérification, reprise « lourde » |

Ansible ne remplace pas la remédiation temps réel : il (re)construit l'environnement et rejoue les opérations lourdes.

## Prérequis

`ansible-core`, Docker + `docker compose`. Se placer dans `ansible/`.

## Commandes

```bash
ansible-playbook -i inventory.ini deploy.yml    # app d'origine (frontend 8085, TG_GAME_MODE=0, ROLE=primary) + module (passerelle 8080, cockpit 8088, canari transaction)
ansible-playbook -i inventory.ini verify.yml    # /health passerelle, login alice, paiement de 1 € via la passerelle (échoue si != 200)
ansible-playbook -i inventory.ini recover.yml   # rejoue db/init.sql, relance api/frontend/passerelle si non sains, puis verify.yml
```

Surcharge : `-e demo_password=autre`, `-e check_recipient=MERCHANT-01`. Le paiement de test cible un marchand autorisé par l'API (SHOP-42), car un destinataire inconnu est refusé (404).

## Notes

- Le Prometheus de l'app est déplacé sur 9091 (le module utilise 9090).
- `prometheus`, `orchestrator` et `assistant` de l'app sont lancés en `--no-deps` : le nginx du frontend les exige, mais sans `detector` l'orchestrateur d'origine reste passif et seul celui du module remédie.
- Le canari et `verify.yml` paient avec le compte de démo : il doit être approvisionné (sinon 402, fonds insuffisants).
- `recover.yml` est idempotent : `init.sql` n'utilise que `CREATE ... IF NOT EXISTS`.
- `deploy.yml` reconstruit les images (`--build`) : prévoir quelques minutes la première fois.
