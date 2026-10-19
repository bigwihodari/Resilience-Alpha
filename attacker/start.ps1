# Console Attaquant — lancement (Windows / PowerShell)
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[ok] .env cree. >> Edite TARGET_URL / TARGET_HOST si tu vises un autre poste."
}

docker compose up -d --build

function Get-EnvVal($name, $default) {
    if (Test-Path ".env") {
        $line = Select-String -Path ".env" -Pattern "^$name=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($line) { return (($line.Line -split "=", 2)[1]).Trim() }
    }
    return $default
}
$port = Get-EnvVal "ATTACKER_PORT" "8090"
$target = Get-EnvVal "TARGET_URL" "http://host.docker.internal:8080"

Write-Host ""
Write-Host "==================================================================="
Write-Host "  CONSOLE ATTAQUANT lancee."
Write-Host "   >> Console (tout-en-un) : http://localhost:$port"
Write-Host "   >> Cible configuree     : $target"
Write-Host "==================================================================="
