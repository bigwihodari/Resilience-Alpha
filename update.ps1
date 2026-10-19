# Resilience-Alpha — mise à jour du SERVEUR HOST. Windows / PowerShell.
# git pull + reconstruction/redémarrage propre (même si la stack tourne déjà).
$ErrorActionPreference = "Stop"
Write-Host "[..] Recuperation du code (git pull)..."
git pull
if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Write-Host "[ok] .env cree" }
function Get-EnvVal($n, $d) {
    if (Test-Path ".env") {
        $l = Select-String -Path ".env" -Pattern "^$n=" -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($l) { return (($l.Line -split "=", 2)[1]).Trim() }
    }
    return $d
}
$role = Get-EnvVal "ROLE" "primary"
Write-Host "[..] Reconstruction et redemarrage (role : $role)..."
docker compose up -d --build --remove-orphans
Write-Host ""
Write-Host "[ok] Serveur HOST a jour (role : $role). Etat :"
docker compose ps
