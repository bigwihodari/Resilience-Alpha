# Resilience-Alpha — lancement rapide (Windows / PowerShell)
$ErrorActionPreference = "Stop"

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "[ok] .env cree depuis .env.example"
}

Write-Host "[..] Construction et demarrage des conteneurs..."
docker compose up -d --build

function Get-EnvPort($name, $default) {
    if (Test-Path ".env") {
        $line = Select-String -Path ".env" -Pattern "^$name=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($line) { return (($line.Line -split "=", 2)[1]).Trim() }
    }
    return $default
}
$front = Get-EnvPort "FRONTEND_PORT" "8080"
$api   = Get-EnvPort "API_PORT" "8000"
$graf  = Get-EnvPort "GRAFANA_PORT" "3000"
$prom  = Get-EnvPort "PROMETHEUS_PORT" "9090"

Write-Host ""
Write-Host "==================================================================="
Write-Host "  RESILIENCE-ALPHA (poste HOTE) est lance."
Write-Host "  >> TOUT est accessible depuis l'application de paiement :"
Write-Host "       http://localhost:$front       (connexion : alice / password123)"
Write-Host ""
Write-Host "  Panels (aussi listes dans le Hub de l'application) :"
Write-Host "   - Paiement / Hub ....... http://localhost:$front"
Write-Host "   - Cockpit resilience .... http://localhost:$front/cockpit"
Write-Host "   - API (Swagger) ......... http://localhost:$api/docs"
Write-Host "   - Grafana ............... http://localhost:$graf   (admin / admin)"
Write-Host "   - Prometheus ............ http://localhost:$prom/targets"
Write-Host "   - Logs (Loki) ........... http://localhost:$graf/explore"
Write-Host "==================================================================="
