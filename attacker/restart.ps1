# Console Attaquant - REDEMARRE en appliquant le .env (apres modif de la cible).
$ErrorActionPreference = "Stop"
Write-Host "[..] Redemarrage avec prise en compte du .env (recreate)..."
docker compose up -d --force-recreate
Write-Host "[ok] Console attaquant redemarree."
docker compose ps
