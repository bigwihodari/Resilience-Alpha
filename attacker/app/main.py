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
    return game.heist(body.get("amount"), body.get("source", "courant"), body.get("livret_id"))


@app.post("/api/game/target")
def game_target(body: dict = Body(default={})):
    return game.set_target(body.get("username", ""))


@app.get("/api/game/suspicion")
def game_suspicion():
    return game.suspicion()


@app.get("/api/game/shop")
def game_shop():
    return game.shop()


@app.post("/api/game/shop/buy")
def game_shop_buy(body: dict = Body(default={})):
    return game.buy(body.get("ukey", ""))


@app.get("/api/intel/offers")
def intel_offers():
    return game.intel_offers()


@app.post("/api/intel/offers/{offer_id}/buy")
def intel_buy(offer_id: int):
    return game.buy_intel(offer_id)


@app.get("/api/game/phishing")
def phishing_list():
    return game.phishing_list()


@app.post("/api/game/phishing")
def phishing_create(body: dict = Body(default={})):
    return game.phishing(body.get("title", "Enchere exceptionnelle"), body.get("item_value", 5000),
                         body.get("min_bid", 100), body.get("lure", ""), body.get("targets", []))


@app.post("/api/game/phishing/{campaign_id}/close")
def phishing_close(campaign_id: int):
    return game.phishing_close(campaign_id)


@app.get("/api/chat/rooms")
def chat_rooms():
    return game.chat_rooms()


@app.get("/api/chat/rooms/{room_id}/messages")
def chat_messages(room_id: int, after: int = 0):
    return game.chat_messages(room_id, after)


@app.post("/api/chat/rooms/{room_id}/messages")
def chat_post(room_id: int, body: dict = Body(default={})):
    return game.chat_post(room_id, body.get("body", ""))


@app.get("/api/game/auctions")
def game_auctions():
    return game.auctions()


@app.post("/api/game/bid")
def game_bid(body: dict = Body(default={})):
    return game.bid(body.get("auction_id"), body.get("amount", 0))


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
