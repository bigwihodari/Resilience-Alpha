#!/usr/bin/env bash
# Déchiffre les secrets (SOPS + age) vers .env, au moment du déploiement.
set -e
command -v sops >/dev/null 2>&1 || { echo "sops requis — voir SECURITE.md"; exit 1; }
[ -f secrets/secrets.sops.env ] || { echo "secrets/secrets.sops.env absent (chiffrer d'abord)"; exit 1; }
sops -d secrets/secrets.sops.env > .env
echo "[ok] .env généré depuis secrets/secrets.sops.env (SOPS/age)."
