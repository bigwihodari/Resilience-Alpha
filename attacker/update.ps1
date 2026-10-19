# Console Attaquant — mise à jour. Windows / PowerShell.
$ErrorActionPreference = "Stop"
Write-Host "[..] git pull..."
git pull
docker compose up -d --build
Write-Host "[ok] Console attaquant a jour."
docker compose ps
