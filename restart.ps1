# Resilience-Alpha - REDEMARRE le serveur HOST en appliquant le .env.
# A utiliser apres avoir modifie des valeurs (IP, ports, ROLE, PEER_API_URL...).
# (docker restart ne relit pas le .env ; il faut recreer les conteneurs.)
$ErrorActionPreference = "Stop"
Write-Host "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
Write-Host "[ok] Redemarre."
docker compose ps
