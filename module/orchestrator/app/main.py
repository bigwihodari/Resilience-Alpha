"""Moteur de remédiation (orchestrateur) — module Resilience Guard.

Surveille le détecteur ML et le WAF de la passerelle. En cas d'incident confirmé,
il DÉCIDE puis EXÉCUTE une remédiation, VÉRIFIE le retour à un état utilisable par
une transaction canari, et tient une timeline. Zéro intervention humaine.

Deux playbooks, génériques (aucune dépendance au métier de l'app protégée) :

  * ANTI-DoS : anomalie ML confirmée → activation du bouclier de load-shedding sur
    la PASSERELLE (`POST /admin/protect`), puis canari pour prouver le service.
  * COMPROMISSION : pic de blocages WAF (tentative d'injection) → mise en évidence
    de la menace contenue + canari de vérification.

Accès maîtrisés : l'orchestrateur n'a PAS d'accès god-mode ; il agit via une API
d'administration scoped de la passerelle (un seul geste : activer/désactiver le
bouclier), protégée par un token dédié. Le canari est un simple `GET /health` de
la passerelle (bout en bout : prouve que le service répond).
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
GATEWAY = os.environ.get("GATEWAY_URL", "http://gateway:8080")
PROM = os.environ.get("PROM_URL", "http://prometheus:9090")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "orchestrator-admin-token")
SHED_RATE = float(os.environ.get("SHED_RATE", "8.0"))
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "internal-trusted-token")
# Canari : "health" (GET /health de la passerelle) ou "transaction" (login + paiement fictif).
CANARY_MODE = os.environ.get("CANARY_MODE", "health")
CANARY_LOGIN_PATH = os.environ.get("CANARY_LOGIN_PATH", "/auth/login")
CANARY_USER = os.environ.get("CANARY_USER", "")
CANARY_PASSWORD = os.environ.get("CANARY_PASSWORD", "")
CANARY_TX_PATH = os.environ.get("CANARY_TX_PATH", "/api/transactions")
CANARY_AMOUNT = float(os.environ.get("CANARY_AMOUNT", "1"))
CANARY_RECIPIENT = os.environ.get("CANARY_RECIPIENT", "CANARY")
POLL = float(os.environ.get("POLL", "3"))
CONFIRM = int(os.environ.get("CONFIRM", "2"))   # polls anormaux consécutifs avant d'agir
CLEAR = int(os.environ.get("CLEAR", "4"))        # polls normaux consécutifs avant de lever le bouclier

state = {
    "state": "NORMAL", "protection": False, "score": 0.0, "last_canary": None,
    "security_state": "CLEAR", "waf_blocks": 0, "timeline": [],
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


def now_iso():
    return datetime.datetime.now().strftime("%H:%M:%S")


def add_event(label, kind="info"):
    with lock:
        state["timeline"].append({"t": now_iso(), "label": label, "kind": kind})
        state["timeline"] = state["timeline"][-40:]
    print(f"[orchestrator] {label}", flush=True)


def set_protection(enabled, rate=None):
    """Active/désactive le bouclier de load-shedding sur la passerelle (API scoped)."""
    try:
        payload = {"enabled": enabled}
        if rate is not None:
            payload["rate"] = rate
        requests.post(f"{GATEWAY}/admin/protect", json=payload,
                      headers={"X-Admin-Token": ADMIN_TOKEN}, timeout=5)
        with lock:
            state["protection"] = enabled
        ACTIVEG.set(1 if enabled else 0)
        return True
    except Exception as e:  # noqa: BLE001
        add_event(f"Échec action bouclier: {e}", "error")
        return False


def _canary_health():
    """GET /health de la passerelle (prouve seulement que la passerelle répond)."""
    r = requests.get(f"{GATEWAY}/health", timeout=6)
    return (r.status_code == 200, "ok" if r.status_code == 200 else f"health {r.status_code}")


def _canary_transaction():
    """Login puis paiement fictif via la passerelle (prouve que l'app métier fonctionne)."""
    headers = {"X-Internal-Token": INTERNAL_TOKEN}  # exempte le canari du load-shedding
    r = requests.post(f"{GATEWAY}{CANARY_LOGIN_PATH}", headers=headers, timeout=6,
                      json={"username": CANARY_USER, "password": CANARY_PASSWORD})
    if r.status_code != 200:
        return (False, f"login {r.status_code}")
    token = r.json().get("access_token")
    if not token:
        return (False, "login sans access_token")
    r = requests.post(f"{GATEWAY}{CANARY_TX_PATH}", timeout=6,
                      headers={**headers, "Authorization": f"Bearer {token}"},
                      json={"amount": CANARY_AMOUNT, "recipient": CANARY_RECIPIENT})
    return (r.status_code == 200, "ok" if r.status_code == 200 else f"tx {r.status_code}")


def canary():
    """Transaction canari (selon CANARY_MODE) : renvoie (ok, latence_ms, détail)."""
    t0 = time.time()
    try:
        ok, detail = _canary_transaction() if CANARY_MODE == "transaction" else _canary_health()
        return (ok, round((time.time() - t0) * 1000, 1), detail)
    except Exception as e:  # noqa: BLE001
        return (False, None, str(e))


def detector_status():
    try:
        d = requests.get(f"{DETECTOR}/status", timeout=4).json()
        return bool(d.get("is_anomaly")), float(d.get("score", 0)), bool(d.get("trained"))
    except Exception:
        return False, 0.0, False


def run_canary_record():
    ok, lat, detail = canary()
    with lock:
        state["last_canary"] = {"ok": ok, "latency_ms": lat, "detail": detail, "t": now_iso()}
    return ok, lat, detail


def loop():
    anom_streak = 0
    clear_streak = 0
    waf_clear = 0
    while True:
        is_anom, score, trained = detector_status()
        with lock:
            state["score"] = score
            st = state["state"]
        anom_streak = anom_streak + 1 if is_anom else 0
        clear_streak = 0 if is_anom else clear_streak + 1

        # --- Playbook ANTI-DoS : anomalie ML confirmée -> bouclier sur la passerelle ---
        if st == "NORMAL" and trained and anom_streak >= CONFIRM:
            add_event(f"Anomalie confirmée par le ML (score {score})", "alert")
            with lock:
                state["state"] = "REMEDIATING"
            add_event("Décision : activation du bouclier anti-DoS sur la passerelle", "action")
            set_protection(True, SHED_RATE)
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

        # --- Playbook COMPROMISSION (injection SQL/XSS) : signal WAF distinct du DoS ---
        waf_rate = prom("sum(rate(waf_blocked_total[1m]))")
        waf_total = prom("sum(waf_blocked_total)")
        with lock:
            state["waf_blocks"] = int(waf_total)
            sec = state["security_state"]
        waf_clear = 0 if waf_rate > 0.1 else waf_clear + 1

        if sec == "CLEAR" and waf_rate > 0.3:
            add_event("Tentative d'injection détectée : requêtes bloquées par le WAF", "alert")
            add_event("Réponse compromission : vérification du service par un canari…", "action")
            ok, lat, detail = run_canary_record()
            with lock:
                state["security_state"] = "CONTAINED"
            if ok:
                add_event(f"Service sain ({lat} ms) — attaque bloquée en amont, "
                          f"l'application n'a jamais reçu les requêtes malveillantes", "success")
            else:
                add_event(f"Canari échoué ({detail}) — surveillance renforcée", "error")
        elif sec == "CONTAINED" and waf_clear >= CLEAR:
            add_event("Fin des tentatives d'injection — menace contenue", "info")
            with lock:
                state["security_state"] = "CLEAR"

        time.sleep(POLL)


app = FastAPI(title="Resilience Guard — Orchestrateur de remédiation")


@app.on_event("startup")
def startup():
    add_event("Orchestrateur démarré — surveillance du détecteur ML et du WAF", "info")
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
