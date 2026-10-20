# App Client - lancement (Windows / PowerShell).
$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[ok] .env cree. >> Edite HOST_PRIMARY (adresse du serveur) si besoin."
}
docker compose up -d --build
function Get-EnvVal($n, $d) {
    if (Test-Path ".env") {
        $l = Select-String -Path ".env" -Pattern "^$n=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($l) { return (($l.Line -split "=", 2)[1]).Trim() }
    }
    return $d
}
$port = Get-EnvVal "CLIENT_PORT" "8095"
$h1 = Get-EnvVal "HOST_PRIMARY" "host.docker.internal"
Write-Host ""
Write-Host "==================================================================="
Write-Host "  APP CLIENT lancee."
Write-Host "   >> http://localhost:$port    (login : alice ou bob / password123)"
Write-Host "   >> Serveur cible : $h1"
Write-Host "==================================================================="
