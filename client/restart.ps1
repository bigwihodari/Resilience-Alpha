# App Client - REDEMARRE en appliquant le .env (apres modif des IP serveur).
$ErrorActionPreference = "Stop"
Write-Host "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
Write-Host "[ok] App client redemarree."
docker compose ps
