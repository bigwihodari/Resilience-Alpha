"""Moteur de remédiation (orchestrateur) — Resilience-Alpha.

Surveille le détecteur ML. En cas d'anomalie confirmée, il DÉCIDE puis EXÉCUTE
une remédiation (activation du bouclier anti-DoS sur l'auth), VÉRIFIE le retour
à un état utilisable par une transaction canari, et tient une timeline.
Zéro intervention humaine.

Accès maîtrisés : l'orchestrateur n'a PAS d'accès god-mode aux conteneurs ; il
agit via une API d'administration scoped (un seul geste : activer/désactiver le
bouclier), protégée par un token dédié.
"""
import os
import time
import threading
import datetime

import requests
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST

DETECTOR = os.environ.get("DETECTOR_URL", "http://detector:8000")
AUTH = os.environ.get("AUTH_URL", "http://auth:8000")
API = os.environ.get("API_URL", "http://api:8000")
PROM = os.environ.get("PROM_URL", "http://prometheus:9090")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "orchestrator-admin-token")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "internal-trusted-token")
CANARY_USER = os.environ.get("CANARY_USER", "canary")
CANARY_PASSWORD = os.environ.get("CANARY_PASSWORD", "password123")
POLL = float(os.environ.get("POLL", "3"))
CONFIRM = int(os.environ.get("CONFIRM", "2"))   # polls anormaux consécutifs avant d'agir
CLEAR = int(os.environ.get("CLEAR", "4"))        # polls normaux consécutifs avant de lever le bouclier

# --- Jeu de hacker : détection de compromission (vol/fuite) + réponse IA ---
GAME_COOLDOWN = float(os.environ.get("GAME_COOLDOWN", "120"))   # blocage attaquant (s)
GAME_LOOT_ALERT = float(os.environ.get("GAME_LOOT_ALERT", "200"))  # butin cumulé => alerte
GAME_RECON_RATE_ALERT = float(os.environ.get("GAME_RECON_RATE_ALERT", "0.6"))  # énumération (req/s)
GAME_HEIST_RATE_ALERT = float(os.environ.get("GAME_HEIST_RATE_ALERT", "0.25"))  # retraits (req/s)

state = {
    "state": "NORMAL", "protection": False, "score": 0.0, "last_canary": None,
    "security_state": "CLEAR", "waf_blocks": 0, "last_integrity": None, "timeline": [],
    # Compromission (jeu) : blocage attaquant + bascule secours + protection de l'argent.
    "compromise": "CLEAR", "attacker_blocked": False, "cooldown_remaining": 0.0,
    "failover": False, "loot": 0.0, "loot_neutralized": 0.0,
}
lock = threading.Lock()
ACTIVEG = Gauge("remediation_active", "1 si bouclier de remediation actif")


def prom(query):
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=4)
        res = r.json().get("data", {}).get("result", [])
        return float(res[0]["value"][1]) if res else 0.0
    except Exception:
        return 0.0


def integrity_check():
    try:
        r = requests.get(f"{API}/admin/integrity", headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=6)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def now_iso():
    return datetime.datetime.now().strftime("%H:%M:%S")


def add_event(label, kind="info"):
    with lock:
        state["timeline"].append({"t": now_iso(), "label": label, "kind": kind})
        state["timeline"] = state["timeline"][-40:]
    print(f"[orchestrator] {label}", flush=True)


def set_protection(enabled, rate=8.0):
    try:
        requests.post(f"{AUTH}/admin/protect", json={"enabled": enabled, "rate": rate},
                      headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=5)
        with lock:
            state["protection"] = enabled
        ACTIVEG.set(1 if enabled else 0)
        return True
    except Exception as e:  # noqa: BLE001
        add_event(f"Échec action bouclier: {e}", "error")
        return False


def canary():
    """Transaction canari de bout en bout : login (exempté) + paiement fictif."""
    t0 = time.time()
    try:
        r = requests.post(f"{AUTH}/login", json={"username": CANARY_USER, "password": CANARY_PASSWORD},
                          headers={"X-Internal-Token": INTERNAL_TOKEN}, timeout=6)
        if r.status_code != 200:
            return (False, None, f"login {r.status_code}")
        tok = r.json()["access_token"]
        r2 = requests.post(f"{API}/transactions", json={"amount": 1, "recipient": "CANARY"},
                           headers={"Authorization": f"Bearer {tok}"}, timeout=6)
        lat = round((time.time() - t0) * 1000, 1)
        return (r2.status_code == 200, lat, "ok" if r2.status_code == 200 else f"tx {r2.status_code}")
    except Exception as e:  # noqa: BLE001
        return (False, None, str(e))


def detector_status():
    try:
        d = requests.get(f"{DETECTOR}/status", timeout=4).json()
        return bool(d.get("is_anomaly")), float(d.get("score", 0)), bool(d.get("trained"))
    except Exception:
        return False, 0.0, False


def game_status():
    try:
        return requests.get(f"{API}/game/state", timeout=4).json()
    except Exception:
        return {}


def game_admin(path, payload=None):
    try:
        r = requests.post(f"{API}{path}", json=(payload or {}),
                          headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=6)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def set_degrade(enabled):
    """Bascule réseau : met le principal en dégradé 503 (nginx -> secours). N'a
    d'effet que si l'API tourne avec GAME_DEGRADE=1 (montage 2 PC)."""
    return game_admin("/admin/degrade", {"enabled": bool(enabled)})


def run_canary_record():
    ok, lat, detail = canary()
    with lock:
        state["last_canary"] = {"ok": ok, "latency_ms": lat, "detail": detail, "t": now_iso()}
    return ok, lat, detail


def loop():
    anom_streak = 0
    clear_streak = 0
    waf_clear = 0
    game_clear = 0
    while True:
        is_anom, score, trained = detector_status()
        with lock:
            state["score"] = score
            st = state["state"]
        anom_streak = anom_streak + 1 if is_anom else 0
        clear_streak = 0 if is_anom else clear_streak + 1

        if st == "NORMAL" and trained and anom_streak >= CONFIRM:
            add_event(f"Anomalie confirmée par le ML (score {score})", "alert")
            with lock:
                state["state"] = "REMEDIATING"
            add_event("Décision : activation du bouclier anti-DoS sur l'auth", "action")
            set_protection(True, 8.0)
            with lock:
                state["state"] = "VERIFYING"
            add_event("Vérification : exécution d'une transaction canari…", "info")
            ok, lat, detail = run_canary_record()
            if ok:
                add_event(f"Transaction canari RÉUSSIE ({lat} ms) — service rétabli", "success")
                with lock:
                    state["state"] = "RECOVERED"
            else:
                add_event(f"Canari échoué ({detail}) — nouvel essai au prochain cycle", "error")
                with lock:
                    state["state"] = "REMEDIATING"

        elif st in ("REMEDIATING", "VERIFYING", "RECOVERED"):
            ok, lat, detail = run_canary_record()
            if ok and st != "RECOVERED":
                add_event(f"Transaction canari RÉUSSIE ({lat} ms) — service rétabli", "success")
                with lock:
                    state["state"] = "RECOVERED"
            if clear_streak >= CLEAR:
                add_event("Attaque terminée : désactivation du bouclier", "action")
                set_protection(False)
                with lock:
                    state["state"] = "NORMAL"

        # --- Playbook COMPROMISSION (injection SQL) : signal distinct du DoS ---
        waf_rate = prom("sum(rate(waf_blocked_total[1m]))")
        waf_total = prom("sum(waf_blocked_total)")
        with lock:
            state["waf_blocks"] = int(waf_total)
            sec = state["security_state"]
        waf_clear = 0 if waf_rate > 0.1 else waf_clear + 1

        if sec == "CLEAR" and waf_rate > 0.3:
            add_event("Tentative d'injection SQL : requêtes bloquées par le WAF", "alert")
            add_event("Réponse compromission : contrôle d'intégrité des données…", "action")
            res = integrity_check()
            with lock:
                state["last_integrity"] = res
                state["security_state"] = "CONTAINED"
            if res and res.get("integrity_ok"):
                add_event(f"Intégrité vérifiée : {res['users_count']} comptes, soldes cohérents, "
                          f"aucune donnée altérée", "success")
            elif res:
                add_event(f"ALERTE intégrité : {res.get('suspicious_users')} — restauration requise", "error")
            else:
                add_event("Contrôle d'intégrité indisponible", "error")
        elif sec == "CONTAINED" and waf_clear >= CLEAR:
            add_event("Fin des tentatives d'injection — menace contenue", "info")
            with lock:
                state["security_state"] = "CLEAR"

        # --- Playbook COMPROMISSION-JEU : vol/fuite -> blocage + bascule secours ---
        g = game_status()
        loot = float(g.get("loot", 0) or 0)
        heist_count = int(g.get("heist_count", 0) or 0)
        recon_rate = prom("sum(rate(game_recon_total[1m]))")
        heist_rate = prom("sum(rate(game_heist_total[1m]))")
        with lock:
            state["loot"] = loot
            state["loot_neutralized"] = float(g.get("loot_neutralized", 0) or 0)
            state["attacker_blocked"] = bool(g.get("blocked"))
            state["cooldown_remaining"] = float(g.get("cooldown_remaining", 0) or 0)
            comp = state["compromise"]

        # Signaux de compromission : butin trop gros, OU exploitation + anomalie ML
        # (attaque trop forte), OU énumération/retraits trop rapides (motif suspect).
        exploiting = heist_count > 0 or loot > 0 or recon_rate > 0
        trigger = (loot >= GAME_LOOT_ALERT
                   or (is_anom and exploiting)
                   or recon_rate > GAME_RECON_RATE_ALERT
                   or heist_rate > GAME_HEIST_RATE_ALERT)

        if comp == "CLEAR" and trigger:
            reason = ("butin anormal" if loot >= GAME_LOOT_ALERT else
                      "attaque trop forte (anomalie ML)" if is_anom else
                      "motif d'énumération/retraits suspect")
            add_event(f"COMPROMISSION détectée ({reason}, butin {loot:.0f}€) — réponse IA", "alert")
            with lock:
                state["compromise"] = "BLOCKED"
                state["failover"] = True
            # 1) Bloquer l'attaquant (cooldown visible côté console)
            game_admin("/game/admin/block", {"seconds": GAME_COOLDOWN, "reason": reason})
            add_event(f"Attaquant BLOQUÉ — cooldown {int(GAME_COOLDOWN)}s ; ses attaques sont refusées", "action")
            # 2) Bascule vers le secours (nginx proxy_next_upstream si GAME_DEGRADE=1)
            set_degrade(True)
            add_event("Bascule : le principal (compromis) passe la main au SECOURS", "action")
            # 3) Protéger l'argent : restaurer le butin (secours sain / intégrité)
            cb = game_admin("/game/admin/clawback")
            restored = (cb or {}).get("restored", 0)
            with lock:
                state["loot_neutralized"] = float((cb or {}).get("loot_neutralized", state["loot_neutralized"]))
                state["loot"] = float((cb or {}).get("loot", 0))
            add_event(f"Butin neutralisé ({restored:.0f}€ restaurés) — l'argent volé ne 'gagne' pas", "success")
            # 4) Prouver que le service reste utilisable
            ok, lat, detail = run_canary_record()
            if ok:
                add_event(f"Transaction canari RÉUSSIE ({lat} ms) — service protégé", "success")
            game_clear = 0

        elif comp == "BLOCKED":
            cd = float(g.get("cooldown_remaining", 0) or 0)
            calm = (not is_anom and recon_rate < 0.1 and heist_rate < 0.05 and loot < GAME_LOOT_ALERT)
            game_clear = game_clear + 1 if calm else 0
            if cd <= 0 and game_clear >= CLEAR:
                set_degrade(False)
                with lock:
                    state["compromise"] = "CLEAR"
                    state["failover"] = False
                add_event("Menace levée — retour à la normale, le principal reprend la main", "success")

        time.sleep(POLL)


app = FastAPI(title="Resilience-Alpha — Orchestrateur de remédiation")


@app.on_event("startup")
def startup():
    add_event("Orchestrateur démarré — surveillance du détecteur ML", "info")
    threading.Thread(target=loop, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "orchestrator"}


@app.get("/status")
def status():
    with lock:
        return dict(state)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
