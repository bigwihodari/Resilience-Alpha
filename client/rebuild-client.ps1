# App Client - reconstruction complete (temps reel / WebSocket).
# A lancer dans une fenetre PowerShell NORMALE sur le PC client (pas en SSH).
# Pre-tire les images de base avant le build pour eviter le bug du
# credential-helper Docker Desktop sous Windows.
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

Write-Host "[1/4] Mise a jour du code (git pull)..."
git pull

Write-Host "[2/4] Pre-telechargement des images de base..."
docker pull node:20-alpine
docker pull nginx:1.27-alpine

Write-Host "[3/4] Reconstruction de l'app client..."
docker compose up -d --build

Write-Host "[4/4] Etat des conteneurs :"
docker compose ps

# Verification du WebSocket : un handshake reussi renvoie "101".
# Le port de l'app client est lu dans .env (CLIENT_PORT), defaut 8095.
$port = 8095
if (Test-Path ".\.env") {
    $m = Select-String -Path ".\.env" -Pattern "^\s*CLIENT_PORT\s*=\s*(\d+)" | Select-Object -First 1
    if ($m) { $port = [int]$m.Matches[0].Groups[1].Value }
}
Write-Host ""
Write-Host "Verification du WebSocket (/ws) sur le port $port..."
$key = "dGhlIHNhbXBsZSBub25jZQ=="
try {
    $line = (& curl.exe -s -i -N -o - `
        -H "Connection: Upgrade" -H "Upgrade: websocket" `
        -H "Sec-WebSocket-Version: 13" -H "Sec-WebSocket-Key: $key" `
        "http://localhost:$port/ws") | Select-String -Pattern "^HTTP" | Select-Object -First 1
    if ($line -match "101") {
        Write-Host "[ok] WebSocket actif : $line"
    } else {
        Write-Host "[!!] Reponse inattendue : $line"
        Write-Host "     (le serveur hote est-il bien lance et joignable ?)"
    }
} catch {
    Write-Host "[!!] Impossible de tester le WebSocket : $($_.Exception.Message)"
}

Write-Host ""
Write-Host "Termine. Ouvre l'app client, fais un paiement depuis l'autre client :"
Write-Host "le solde doit se mettre a jour tout seul, sans rafraichir la page."
