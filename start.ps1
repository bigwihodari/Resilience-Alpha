# Resilience-Alpha — lancement rapide (Windows / PowerShell)
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[ok] .env créé depuis .env.example"
}

Write-Host "[..] Construction et démarrage des conteneurs..."
docker compose up -d --build

Write-Host ""
Write-Host "[ok] Resilience-Alpha est lancé."
Write-Host "     Frontend : http://localhost:8080   (alice / password123)"
Write-Host "     API doc  : http://localhost:8000/docs"
