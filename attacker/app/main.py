"""Console Attaquant — Resilience-Alpha (poste Attaquant).

Une seule application : API de contrôle d'attaque + console web + indicateurs,
avec tous les liens de supervision de la cible. Rien à chercher ailleurs.
"""
import os
import pathlib

from fastapi import FastAPI, Body
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from attacks import AttackController

TARGET_URL = os.environ.get("TARGET_URL", "http://host.docker.internal:8080")
TARGET_HOST = os.environ.get("TARGET_HOST", "") or TARGET_URL.split("//")[-1].split(":")[0]

ctrl = AttackController(TARGET_URL)
app = FastAPI(title="Resilience-Alpha — Console Attaquant")

_HERE = pathlib.Path(__file__).parent
CONSOLE_HTML = (_HERE / "console.html").read_text(encoding="utf-8")
app.mount("/static", StaticFiles(directory=_HERE / "static"), name="static")


@app.get("/", response_class=HTMLResponse)
def console():
    html = CONSOLE_HTML.replace("__TARGET_URL__", TARGET_URL).replace("__TARGET_HOST__", TARGET_HOST)
    return HTMLResponse(html)


@app.get("/api/config")
def config():
    return {"target_url": TARGET_URL, "target_host": TARGET_HOST}


@app.get("/api/status")
def status():
    return ctrl.status()


@app.post("/api/attack/start")
def attack_start(body: dict = Body(default={})):
    ok = ctrl.start(body.get("type", "dos"), body.get("intensity", 10), body.get("duration", 60))
    return {"started": ok, **ctrl.status()}


@app.post("/api/attack/stop")
def attack_stop():
    ctrl.stop()
    return {"stopped": True, **ctrl.status()}


@app.get("/metrics")
def metrics():
    st = ctrl.status()
    lines = [
        "# HELP attacker_requests_sent Requêtes envoyées vers la cible",
        "# TYPE attacker_requests_sent counter",
        f"attacker_requests_sent {st['sent']}",
        f"attacker_errors {st['errors']}",
        f"attacker_refused {st['refused']}",
        f"attacker_ok {st['ok']}",
        f"attacker_avg_latency_ms {st['avg_latency_ms']}",
        f"attacker_running {1 if st['running'] else 0}",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/plain")
