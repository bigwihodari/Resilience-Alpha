# Resilience-Alpha — ARRÊTE TOUT (host principal/secours + client + attaquant).
# Les données (volumes) sont conservées. Windows / PowerShell.
Write-Host "[..] Arret du serveur HOST..."
docker compose down
Write-Host "[..] Arret du host de secours (si present)..."
try { docker compose -f docker-compose.backup.yml down } catch {}
Write-Host "[..] Arret de l'app client (si presente)..."
try { docker compose -f client/docker-compose.yml down } catch {}
Write-Host "[..] Arret de la console attaquant (si presente)..."
try { docker compose -f attacker/docker-compose.yml down } catch {}
Write-Host "[ok] Tout est arrete (les donnees sont conservees)."
Write-Host "    Pour effacer aussi les donnees : docker compose down -v (par stack)."
