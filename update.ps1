# Resilience-Alpha — mise à jour (Windows / PowerShell)
# Récupère le code, reconstruit et redémarre proprement, même si la stack tourne déjà.
$ErrorActionPreference = "Stop"

Write-Host "[..] Récupération du code (git pull)..."
git pull

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[ok] .env créé depuis .env.example"
}

Write-Host "[..] Reconstruction et redémarrage des conteneurs modifiés..."
docker compose up -d --build --remove-orphans

Write-Host ""
Write-Host "[ok] Mise à jour terminée. État :"
docker compose ps
