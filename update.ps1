# Resilience-Alpha - mise a jour COMPLETE (host + client + attaquant). Windows / PowerShell.
# git pull + reconstruction + recreation forcee (sinon un changement de conf nginx/env
# n'est pas toujours applique par `up --build` seul).
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot
Write-Host "[..] Recuperation du code (git pull)..."
git pull --ff-only; if (-not $?) { git pull }
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "[ok] .env cree" }

Write-Host "[..] HOST (api / auth / frontend / orchestrateur / observabilite)..."
docker compose up -d --build --force-recreate --remove-orphans

if (Test-Path "client") {
    Write-Host "[..] CLIENT (le jeu)..."
    Push-Location client; docker compose up -d --build --force-recreate; Pop-Location
}
if (Test-Path "attacker") {
    Write-Host "[..] ATTAQUANT (console)..."
    Push-Location attacker; docker compose up -d --build --force-recreate; Pop-Location
}

Write-Host ""
Write-Host "[ok] Tout est a jour. Etat du host :"
docker compose ps
Write-Host ""
Write-Host "Jeu (client)   : http://localhost:8095"
Write-Host "App / cockpit  : http://localhost:8080"
Write-Host "Console attaq. : http://localhost:8090"
