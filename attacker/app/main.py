"""Console Attaquant — Resilience-Alpha (poste Attaquant).

Une seule application : API de contrôle d'attaque + console web + indicateurs,
avec tous les liens de supervision de la cible. Rien à chercher ailleurs.
"""
import os
import pathlib

from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from attacks import AttackController, GameController

TARGET_URL = os.environ.get("TARGET_URL", "http://host.docker.internal:8080")
TARGET_HOST = os.environ.get("TARGET_HOST", "") or TARGET_URL.split("//")[-1].split(":")[0]

ctrl = AttackController(TARGET_URL)
game = GameController(TARGET_URL, ctrl)
app = FastAPI(title="Resilience-Alpha — Console Attaquant")

_HERE = pathlib.Path(__file__).parent
CONSOLE_HTML = (_HERE / "console.html").read_text(encoding="utf-8")
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")


_GUIDE = _HERE / "GUIDE-ATTAQUANT.html"


@app.get("/", response_class=HTMLResponse)
def console():
    html = CONSOLE_HTML.replace("__TARGET_URL__", TARGET_URL).replace("__TARGET_HOST__", TARGET_HOST)
    return HTMLResponse(html)


@app.get("/guide", response_class=HTMLResponse)
def guide():
    """Doc pédagogique : comment marche le mode jeu (vol) côté attaquant."""
    if _GUIDE.exists():
        return HTMLResponse(_GUIDE.read_text(encoding="utf-8"))
    return HTMLResponse("<p>Guide indisponible.</p>", status_code=404)


@app.get("/api/config")
def config():
    return {"target_url": TARGET_URL, "target_host": TARGET_HOST}


@app.get("/api/status")
def status():
    return ctrl.status()


@app.post("/api/attack/start")
def attack_start(body: dict = Body(default={})):
    # `types` (liste) a priorité, sinon `type` (str), sinon défaut ["dos_auth"].
    if game.is_blocked():
        return {"started": [], "blocked": True, **ctrl.status()}
    types = body.get("types")
    if not types:
        single = body.get("type")
        types = [single] if single else ["dos_auth"]
    started = ctrl.start(types, body.get("intensity", 10), body.get("duration", 60))
    return {"started": started, **ctrl.status()}


@app.post("/api/attack/start_all")
def attack_start_all(body: dict = Body(default={})):
    if game.is_blocked():
        return {"started": [], "blocked": True, **ctrl.status()}
    started = ctrl.start_all(body.get("intensity", 10), body.get("duration", 60))
    return {"started": started, **ctrl.status()}


# ---------------- Zone jeu : reconnaissance / opération ----------------
@app.get("/api/game/state")
def game_state():
    return game.state()


@app.post("/api/game/recon")
def game_recon():
    return game.recon()


@app.post("/api/game/heist")
def game_heist(body: dict = Body(default={})):
    return game.heist(body.get("amount"), body.get("source", "courant"))


@app.post("/api/game/target")
def game_target(body: dict = Body(default={})):
    return game.set_target(body.get("username", ""))


@app.post("/api/attack/stop")
def attack_stop(body: dict = Body(default={})):
    stopped = ctrl.stop(body.get("type"))
    return {"stopped": stopped, **ctrl.status()}


@app.get("/metrics")
def metrics():
    st = ctrl.status()
    lines = [
        "# HELP attacker_requests_sent Requêtes envoyées vers la cible",
        "# TYPE attacker_requests_sent counter",
        # Agrégats (Prometheus/Grafana continuent de fonctionner).
        f"attacker_requests_sent {st['sent']}",
        f"attacker_errors {st['errors']}",
        f"attacker_refused {st['refused']}",
        f"attacker_ok {st['ok']}",
        f"attacker_avg_latency_ms {st['avg_latency_ms']}",
        f"attacker_running {1 if st['running'] else 0}",
    ]
    # Jauges par vecteur, avec un label `vector="..."`.
    lines.append("# HELP attacker_vector_sent Requêtes envoyées par vecteur")
    lines.append("# TYPE attacker_vector_sent counter")
    for name, a in st.get("attacks", {}).items():
        lines.append(f'attacker_vector_sent{{vector="{name}"}} {a["sent"]}')
        lines.append(f'attacker_vector_errors{{vector="{name}"}} {a["errors"]}')
        lines.append(f'attacker_vector_refused{{vector="{name}"}} {a["refused"]}')
        lines.append(f'attacker_vector_ok{{vector="{name}"}} {a["ok"]}')
        lines.append(f'attacker_vector_avg_latency_ms{{vector="{name}"}} {a["avg_latency_ms"]}')
        lines.append(f'attacker_vector_running{{vector="{name}"}} {1 if a["running"] else 0}')
    return Response("\n".join(lines) + "\n", media_type="text/plain")
