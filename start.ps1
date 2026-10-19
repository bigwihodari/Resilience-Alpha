# Resilience-Alpha — SERVEUR HOST (principal ou secours). Windows / PowerShell.
$ErrorActionPreference = "Stop"
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "[ok] .env cree depuis .env.example" }

function Get-EnvVal($n, $d) {
    if (Test-Path ".env") {
        $l = Select-String -Path ".env" -Pattern "^$n=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($l) { return (($l.Line -split "=", 2)[1]).Trim() }
    }
    return $d
}
$role = Get-EnvVal "ROLE" "primary"
$peer = Get-EnvVal "PEER_API_URL" ""
if ($role -eq "backup" -and [string]::IsNullOrWhiteSpace($peer)) {
    Write-Host "[!] ROLE=backup mais PEER_API_URL est vide dans .env (ex. http://192.168.137.1:8000)."
}

Write-Host "[..] Demarrage du serveur HOST (role : $role)..."
docker compose up -d --build

$front = Get-EnvVal "FRONTEND_PORT" "8080"
$api = Get-EnvVal "API_PORT" "8000"
$graf = Get-EnvVal "GRAFANA_PORT" "3000"
$prom = Get-EnvVal "PROMETHEUS_PORT" "9090"
Write-Host ""
Write-Host "==================================================================="
Write-Host "  RESILIENCE-ALPHA — SERVEUR HOST (role : $role) lance."
Write-Host "  >> Cockpit / supervision :  http://localhost:$front"
Write-Host "   - Cockpit ........... http://localhost:$front/cockpit"
Write-Host "   - API (Swagger) ..... http://localhost:$api/docs"
Write-Host "   - Grafana ........... http://localhost:$graf   (admin / admin)"
Write-Host "   - Prometheus ........ http://localhost:$prom/targets"
if ($role -eq "backup") { Write-Host "   - Replique le principal : $peer" }
Write-Host "==================================================================="
