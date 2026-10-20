# 🚀 Guide de lancement — Resilience-Alpha (montage 5 PC)

Guide simple et pas-à-pas pour lancer toute la démo sur vos 5 ordinateurs.
À lire dans l'ordre. Chaque PC a **un seul rôle** ; allez directement à votre partie.

| PC | Rôle | Partie du guide |
|---|---|---|
| 🖥️ HOST-PRINCIPAL | Serveur principal + cockpit | **Partie 2** |
| 🖥️ HOST-BACKUP | Serveur de secours | **Partie 3** |
| 👤 CLIENT-A / CLIENT-B | App de paiement | **Partie 4** |
| ⚔️ ATTAQUANT | Console d'attaque | **Partie 5** |

---

## Partie 0 — À faire sur CHAQUE PC (une fois)

1. **Docker Desktop installé ET démarré.** Icône baleine 🐳 en bas à droite → « Engine running ».
   - ⚠️ **Erreur la plus fréquente** : si vous voyez `error during connect ... dockerDesktopLinuxEngine ... cannot find the file`, c'est que **Docker Desktop n'est pas lancé**. Ouvrez-le, attendez 1 min, réessayez.
2. **Git installé.**
3. **Récupérer le projet** (tant que vous avez internet — WiFi de l'école) :
   ```bash
   git clone https://github.com/bigwihodari/Resilience-Alpha.git
   cd Resilience-Alpha
   ```
   (Collègue sans GitHub : dézipper `Resilience-Alpha-complet.zip`, puis ouvrir le dossier.)
4. **Premier lancement = besoin d'internet** (pour télécharger/construire les images Docker).
   Faites donc le tout premier `start` **avant** de passer sur le point d'accès du groupe.

---

## Partie 1 — Le réseau du groupe (point d'accès)

### Faut-il un point d'accès spécial, ou le WiFi de l'école suffit ?
➡️ **On utilise le point d'accès mobile de Windows du PC principal — PAS le WiFi de l'école.**
Le WiFi de l'école isole en général les PC les uns des autres (ils ne peuvent pas se « voir »),
donc la démo entre machines ne marcherait pas. Le sujet **impose** d'ailleurs ce point d'accès.

### A. Ouvrir le point d'accès (SUR LE PC PRINCIPAL uniquement)
1. **Paramètres → Réseau et Internet → Point d'accès sans fil mobile** → **Activer**.
2. Cliquer **Modifier** : nom du réseau (SSID) = `RESILIENCE-G<n>` (remplacez `<n>` par votre n° de groupe), choisir un mot de passe.
3. Laisser « Partager ma connexion depuis : Wi-Fi » (le principal peut rester sur le WiFi de l'école pour internet — il partage cette connexion).
   > Raccourci : `Win + A` (volet des réglages rapides) → **Point d'accès sans fil mobile**.

### B. Connecter les 4 autres PC
Backup, CLIENT-A, CLIENT-B, Attaquant : se connecter au Wi-Fi **`RESILIENCE-G<n>`** (avec le mot de passe).

### C. Trouver les adresses IP (sur chaque PC)
Ouvrir PowerShell et taper :
```powershell
ipconfig | findstr IPv4
```
- Le **PC principal** (qui héberge le point d'accès) a l'adresse **`192.168.137.1`**.
- Les autres PC ont une adresse `192.168.137.x` (ex. `.2`, `.3`, …). **Notez-les** :
  - IP du **backup** : `192.168.137.___`
  - IP de **CLIENT-A** / **CLIENT-B** : pas besoin (ce sont eux qui appellent le serveur).

### D. Pare-feu (si les autres PC n'arrivent pas à joindre le serveur)
Sur le **principal** et le **backup**, autoriser les ports entrants (PowerShell **administrateur**) :
```powershell
netsh advfirewall firewall add rule name="Resilience-Alpha" dir=in action=allow protocol=TCP localport=8000,8001,8080,3000,9090
```
Et vérifier que le réseau `RESILIENCE-G<n>` est bien en profil **Privé**
(Paramètres → Réseau → Wi-Fi → propriétés → « Réseau privé »).

---

## Partie 2 — 🖥️ HOST-PRINCIPAL (serveur principal)

C'est le PC qui héberge le point d'accès (IP `192.168.137.1`) et fait tourner le serveur + le cockpit.

1. Créer le fichier `.env` (à la racine du projet) :
   ```
   ROLE=primary
   JWT_SECRET=choisir-un-secret-commun
   REPL_TOKEN=choisir-un-token-commun
   ```
   > Notez `JWT_SECRET` et `REPL_TOKEN` : ils devront être **identiques** sur le backup.
2. Lancer :
   - Windows : `.\start.ps1`
   - Git Bash : `./start.sh`
3. Vérifier : ouvrir **http://localhost:8080** → cockpit (connexion `alice` / `password123`).

Mettre à jour : `.\update.ps1` · Arrêter tout : `.\stop.ps1`

---

## Partie 3 — 🖥️ HOST-BACKUP (serveur de secours)

PC connecté au point d'accès du groupe. Il réplique le principal et prend le relais s'il tombe.

1. Créer le fichier `.env` (à la racine) — **mêmes secrets que le principal** :
   ```
   ROLE=backup
   PEER_API_URL=http://192.168.137.1:8000
   JWT_SECRET=le-meme-que-le-principal
   REPL_TOKEN=le-meme-que-le-principal
   ```
2. Lancer : `.\start.ps1` (il affichera « rôle : backup »).
3. Vérifier qu'il réplique : `http://localhost:8080/cockpit` doit fonctionner localement.

---

## Partie 4 — 👤 CLIENT-A et CLIENT-B (app de paiement)

Chaque client installe l'**app client** et se connecte au serveur.

1. Aller dans le dossier client :
   ```bash
   cd client
   ```
2. Créer le fichier `client/.env` avec les adresses des serveurs :
   ```
   HOST_PRIMARY=192.168.137.1   HOST_PRIMARY_API_PORT=8000   HOST_PRIMARY_AUTH_PORT=8001
   HOST_BACKUP=192.168.137.<ip-du-backup>   HOST_BACKUP_API_PORT=8000   HOST_BACKUP_AUTH_PORT=8001
   ```
   (Remplacez `<ip-du-backup>` par l'IP notée en Partie 1-C.)
3. Lancer : `.\start.ps1`
4. Ouvrir **http://localhost:8095** et se connecter :
   - sur **CLIENT-A** : `alice` / `password123`
   - sur **CLIENT-B** : `bob` / `password123`
5. Payer un ami : chercher son nom (ex. `bob`), entrer un montant, **Payer**.

Mettre à jour : `.\update.ps1` · Arrêter : `.\stop.ps1`

---

## Partie 5 — ⚔️ ATTAQUANT (console d'attaque)

PC distinct qui attaque le **serveur principal** (dans votre labo uniquement).

1. Aller dans le dossier attaquant :
   ```bash
   cd attacker
   ```
2. Créer le fichier `attacker/.env` :
   ```
   TARGET_URL=http://192.168.137.1:8080
   TARGET_HOST=192.168.137.1
   ```
3. Lancer : `.\start.ps1`
4. Ouvrir **http://localhost:8090** → choisir l'attaque (Saturation / Injection SQL), régler l'intensité, **Lancer**.

Mettre à jour : `.\update.ps1` · Arrêter : `.\stop.ps1`

---

## Partie 6 — Ordre d'allumage recommandé (le jour J)

1. **Principal** : ouvrir le point d'accès + `start.ps1` (vérifier le cockpit).
2. **Backup** : se connecter au point d'accès + `start.ps1` (vérifier qu'il réplique).
3. **Clients A et B** : se connecter + configurer `client/.env` + `start.ps1` + se connecter.
4. **Attaquant** : se connecter + configurer `attacker/.env` + `start.ps1`.
5. **Démo** : les clients se paient ; l'attaquant frappe le principal ; le cockpit montre
   détection → remédiation ; si le principal tombe, les clients basculent sur le backup.

---

## Partie 7 — Problèmes fréquents

| Symptôme | Cause / solution |
|---|---|
| `error during connect ... dockerDesktopLinuxEngine` | **Docker Desktop pas lancé.** Ouvrez-le, attendez « Engine running », réessayez. |
| Un client n'atteint pas le serveur | Mauvaise IP dans `client/.env`, ou **pare-feu** (Partie 1-D), ou réseau non « Privé », ou pas connecté au bon Wi-Fi. |
| « port is already allocated » | Un autre logiciel occupe le port. Changez-le dans `.env` (voir §7 de DEPLOIEMENT.md) puis `.\update.ps1`. |
| Première page lente à charger | Attendez 15-20 s que les conteneurs démarrent, puis rafraîchissez. |
| Repartir de zéro sur un PC | `docker compose down -v` puis `.\start.ps1`. |
| L'assistant IA ne répond pas | Ollama doit tourner sur le PC Hôte (`ollama serve`) avec le modèle `qwen3:8b`. |

---

> ⚠️ Projet pédagogique : données et attaques **fictives**, limitées à votre labo et à vos
> machines. Jamais vers le réseau de l'école, un autre groupe ou internet.
