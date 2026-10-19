# App Client — mise à jour. Windows / PowerShell.
$ErrorActionPreference = "Stop"
Write-Host "[..] git pull..."
git pull
docker compose up -d --build
Write-Host "[ok] App client a jour."
docker compose ps
