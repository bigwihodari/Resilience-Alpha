"""API métier de paiement — Resilience-Alpha.

Traite des transactions fictives. Vérifie les JWT émis par le service auth
(secret partagé). Expose /metrics pour Prometheus (utilisé plus tard par la
détection ML et la supervision).
"""
import os
import re
import time
import json
from collections import deque
import math
import html
import random
import asyncio
import threading
import datetime as dt

import jwt
import requests
from fastapi import FastAPI, HTTPException, Depends, Header, Body, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy import (
    create_engine, Integer, String, Numeric, ForeignKey, DateTime, func, select, text,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from prometheus_fastapi_instrumentator import Instrumentator
from prometheus_client import Counter, Gauge

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALG = "HS256"
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "orchestrator-admin-token")

# Réplication / haute disponibilité
ROLE = os.environ.get("ROLE", "primary")              # primary | backup
PEER_API_URL = os.environ.get("PEER_API_URL", "")     # URL de l'api du pair (principal<->secours)
REPL_TOKEN = os.environ.get("REPL_TOKEN", "repl-secret")
REPL_INTERVAL = float(os.environ.get("REPL_INTERVAL", "2"))
HA_NAME = os.environ.get("HA_NAME", "PRINCIPAL" if ROLE == "primary" else "SECOURS")
# Livret d'epargne : taux applique toutes les SAVINGS_INTERVAL secondes.
# Modifiable EN DIRECT par le banquier (savings_cfg) ; ces env sont les valeurs de depart.
SAVINGS_RATE = float(os.environ.get("SAVINGS_RATE", "0.01"))       # 1% par cycle (demo)
SAVINGS_INTERVAL = float(os.environ.get("SAVINGS_INTERVAL", "30"))  # secondes
savings_cfg = {"rate": SAVINGS_RATE, "interval": SAVINGS_INTERVAL}

# Destinataires externes autorises (marchands/canari). Un paiement vers un nom
# qui n'est NI un client connu NI un marchand de cette liste est refuse (404) :
# evite les "paiements vers des comptes inexistants".
MERCHANTS = set(m.strip() for m in os.environ.get(
    "MERCHANTS", "MERCHANT-01,MERCHANT-02,MERCHANT-03,SHOP-42,CANARY").split(",") if m.strip())

# Condition de victoire du jeu : premier (client OU attaquant) a atteindre la cible.
WIN_TARGET = float(os.environ.get("WIN_TARGET", "1000000"))
game_winner = {"name": None, "camp": None, "networth": 0.0, "at": None}
# Compte "banque" (coffre) : cible de hack haut-risque, exclu du jeu/leaderboard.
BANK_USER = os.environ.get("BANK_USER", "trafficbot")

# ---- Shop & upgrades (jeu idle) : coûts EXPONENTIELS cost = base * growth^niveau ----
# Améliorations GLOBALES (compte). La PRODUCTION se booste par LIVRET (bouton
# Booster sur chaque livret) -> chaque livret a ses propres améliorations.
SHOP = {
    "livret_slot": {"label": "Nouveau livret", "base": 500.0, "growth": 1.6,
                    "desc": "Débloque un livret d'épargne supplémentaire (vide, à booster ensuite)."},
    "security":    {"label": "Coffre-fort", "base": 800.0, "growth": 1.45,
                    "desc": "Sécurité : réduit le risque de te faire voler par un attaquant (par niveau)."},
}
LIVRET_RATE_BASE = 200.0      # coût de base pour booster le taux d'un livret (principal, position 0)
LIVRET_RATE_GROWTH = 1.18     # exponentiel sur le NIVEAU de boost
LIVRET_NUMBER_GROWTH = float(os.environ.get("LIVRET_NUMBER_GROWTH", "5"))  # exponentiel sur le NUMERO du livret
LIVRET_RATE_STEP = 0.005      # +0.5 % de taux par niveau de boost
BASE_LIVRET_SLOTS = 1         # livrets supplémentaires autorisés au départ (hors principal)

# ---- P3.5 : SHOP HACKER (payé avec le butin) — coûts exponentiels ----
# Chaque upgrade atténue un risque ou augmente une capacité du vol.
HSHOP = {
    "stealth":  {"label": "Furtivité", "base": 300.0, "growth": 1.5,
                 "desc": "Réduit la montée de suspicion et la proba de te faire cramer (-10 %/niv)."},
    "proxy":    {"label": "Rotation d'IP / proxy", "base": 400.0, "growth": 1.5,
                 "desc": "Réduit la probabilité de blocage par l'IA (-12 %/niv)."},
    "toolkit":  {"label": "Boîte à outils", "base": 500.0, "growth": 1.55,
                 "desc": "Augmente le plafond de vol par coup (+50 %/niv)."},
    "decoder":  {"label": "Décodeur d'intel", "base": 350.0, "growth": 1.5,
                 "desc": "Recon plus rapide : -1 sonde requise avant un vol, par niveau (min 1)."},
}


def _hk_level(ukey: str) -> int:
    with game_lock:
        return int(game_state.get("hk", {}).get(ukey, 0))


def upg_cost(base, growth, level):
    return round(float(base) * (float(growth) ** int(level)), 2)


def _boost_cost(position, level):
    """Coût du prochain boost d'un livret.

    Exponentiel sur DEUX axes :
    - le NIVEAU de boost déjà atteint (growth ^ level) ;
    - le NUMÉRO du livret (position) : principal=0, livrets suivants 1,2,3…
      → base x (LIVRET_NUMBER_GROWTH ^ position). Plus on possède de livrets,
      plus booster un nouveau livret coûte cher dès le niveau 1.
    """
    base = LIVRET_RATE_BASE * (LIVRET_NUMBER_GROWTH ** int(position))
    return upg_cost(base, LIVRET_RATE_GROWTH, level)


def _upg_level(s, user_id, ukey):
    u = s.scalar(select(Upgrade).where(Upgrade.user_id == user_id, Upgrade.ukey == ukey))
    return int(u.level) if u else 0


def _global_mult(level):
    return 1.0 + 0.10 * int(level)
FAIL_PROMOTE = int(os.environ.get("FAIL_PROMOTE", "3"))       # échecs avant promotion du secours
FAILBACK_CONFIRM = int(os.environ.get("FAILBACK_CONFIRM", "3"))  # cycles OK avant retour au principal
repl_state = {"role": ROLE, "name": HA_NAME, "promoted": ROLE == "primary", "peer": PEER_API_URL,
              "last_sync": None, "fails": 0, "events": []}

# ----------------------------------------------------------------------------
# JEU DE HACKER (zone spéciale de la console attaquant) — chemins EXPLOITABLES
# PAR CONCEPTION, mais entièrement instrumentés (compteurs Prometheus + logs)
# pour que la chaîne IA (detector/orchestrator) puisse détecter l'exploitation.
# Tout est fictif / pédagogique. Les retraits du jeu sont PLAFONNÉS et atomiques.
# ----------------------------------------------------------------------------
GAME_VICTIM = os.environ.get("GAME_VICTIM", "bob")          # compte client ciblé
GAME_HEIST_MAX = float(os.environ.get("GAME_HEIST_MAX", "120"))   # plafond PAR retrait hérité (dino-hijack)
# Plafond CUMULÉ du butin. Dans le jeu idle (course au million), le limiteur n'est
# plus un petit plafond mais le RISQUE (proba de se faire cramer) ; on autorise donc
# le butin à monter jusqu'à l'objectif de victoire.
GAME_LOOT_CAP = float(os.environ.get("GAME_LOOT_CAP", "1000000"))
GAME_RECON_FOR_HEIST = int(os.environ.get("GAME_RECON_FOR_HEIST", "3"))  # recon requis avant vol
GAME_SEED_SAVINGS = float(os.environ.get("GAME_SEED_SAVINGS", "300"))    # livret initial de la victime
# Dégradé/503 des endpoints métier lors d'une bascule (nginx proxy_next_upstream
# -> secours). OFF par défaut (démo mono-machine stable) ; passer GAME_DEGRADE=1
# sur un montage 2 PC avec un vrai secours pour une bascule réseau réelle.
GAME_DEGRADE = os.environ.get("GAME_DEGRADE", "0") == "1"

# ---- P2.7 : mini-jeu Dino (récolte de pièces -> argent, validé serveur) ----
DINO_COIN_VALUE = float(os.environ.get("DINO_COIN_VALUE", "1"))     # € par pièce
DINO_MAX_SCORE = float(os.environ.get("DINO_MAX_SCORE", "2000"))    # plafond score brut / claim
DINO_CLAIM_CAP = float(os.environ.get("DINO_CLAIM_CAP", "5000"))    # plafond € crédité / claim
DINO_COOLDOWN = float(os.environ.get("DINO_COOLDOWN", "8"))         # s entre 2 récoltes / joueur
DINO_MULTS = (1, 5, 10, 100)                                        # multiplicateurs bonus autorisés
# Hack attaquant : détournement du gain Dino d'un client (protégé par l'IA).
DINO_HIJACK_P = float(os.environ.get("DINO_HIJACK_P", "0.45"))          # proba de succès de base
DINO_HIJACK_SHARE = float(os.environ.get("DINO_HIJACK_SHARE", "0.5"))   # part du gain détournée
DINO_HIJACK_BLOCK_P = float(os.environ.get("DINO_HIJACK_BLOCK_P", "0.5"))  # proba de blocage si échec
DINO_HIJACK_COOLDOWN = float(os.environ.get("DINO_HIJACK_COOLDOWN", "60"))  # cooldown si grillé
dino_last = {}  # username -> epoch du dernier claim (anti-rafale)


def _dino_mult(m) -> int:
    """Borne le multiplicateur envoyé par le front à un palier autorisé (anti-triche)."""
    try:
        m = int(m)
    except Exception:  # noqa: BLE001
        m = 1
    allowed = [a for a in DINO_MULTS if a <= m]
    return max(allowed) if allowed else 1


# ---- P3.5 : économie du vol (risque/récompense) ----
# Vol de la BANQUE (trafficbot) : très rentable, très sécurisé ; cramé = perte
# TOTALE du butin + long cooldown. Vol de CLIENTS : plus facile, difficulté
# exponentielle avec la fréquence ET le montant ; cramé = perte ~80 % + claw-back.
HEIST_BANK_MAX = float(os.environ.get("HEIST_BANK_MAX", "50000"))    # plafond/coup sur la banque
HEIST_CLIENT_MAX = float(os.environ.get("HEIST_CLIENT_MAX", "2000"))  # plafond/coup sur un client
HEIST_PVP_MAX = float(os.environ.get("HEIST_PVP_MAX", "5000"))        # plafond/coup sur un attaquant
CATCH_BANK_BASE = float(os.environ.get("CATCH_BANK_BASE", "0.35"))
CATCH_BANK_K = float(os.environ.get("CATCH_BANK_K", "0.55"))          # * (montant / plafond banque)
CATCH_CLIENT_BASE = float(os.environ.get("CATCH_CLIENT_BASE", "0.06"))
CATCH_CLIENT_K_AMT = float(os.environ.get("CATCH_CLIENT_K_AMT", "0.30"))   # * (montant / plafond client)
CATCH_CLIENT_K_FREQ = float(os.environ.get("CATCH_CLIENT_K_FREQ", "0.04"))  # * vols clients récents
CATCH_PVP_BASE = float(os.environ.get("CATCH_PVP_BASE", "0.20"))
BANK_BURN_COOLDOWN = float(os.environ.get("BANK_BURN_COOLDOWN", "300"))  # 5 min si cramé sur la banque
CLIENT_FINE_RATE = float(os.environ.get("CLIENT_FINE_RATE", "0.8"))      # perte 80 % du montant visé
rivals = {}  # handle d'attaquant (hors primaire) -> butin, pour le PvP

# ---- P4 : détection par IP/acteur — suspicion s∈[0,1] + blocage PROBABILISTE ----
# La suspicion monte avec les signaux risqués (vols cramés, rafales, phishing,
# retraits anormaux) et DÉCROÎT avec le temps. Le blocage est PROBABILISTE
# (p = logistique du score, pas 100 %) et ISOLÉ : on ne bloque que l'acteur
# suspecté, jamais les deux attaquants. La rotation d'IP (shop) réduit p ; la
# furtivité réduit la montée du score.
SUSP_DECAY = float(os.environ.get("SUSP_DECAY", "0.01"))    # /s (demi-vie ~70 s)
SUSP_K = float(os.environ.get("SUSP_K", "8"))               # pente de la logistique
SUSP_S0 = float(os.environ.get("SUSP_S0", "0.65"))          # seuil (p=0.5 au score S0)
SUSP_COOLDOWN = float(os.environ.get("SUSP_COOLDOWN", "90"))  # durée du blocage IA (s)
suspicion = {}  # actor -> {score, last, blocked_until, ip, last_reason}
susp_lock = threading.Lock()

# P5 — phishing : proba de détection par l'anti-fraude (monte avec la suspicion)
PHISH_DETECT_BASE = float(os.environ.get("PHISH_DETECT_BASE", "0.25"))


def _proxy_factor() -> float:
    """Rotation d'IP/proxy (shop) : réduit la probabilité de blocage."""
    return max(0.1, 1.0 - 0.12 * _hk_level("proxy"))


def _susp(actor: str) -> dict:
    """Entrée de suspicion de l'acteur, avec décroissance temporelle appliquée."""
    now = time.time()
    with susp_lock:
        e = suspicion.get(actor)
        if e is None:
            e = {"score": 0.0, "last": now, "blocked_until": 0.0, "ip": "", "last_reason": ""}
            suspicion[actor] = e
        dtp = now - e["last"]
        if dtp > 0 and e["score"] > 0:
            e["score"] = round(e["score"] * math.exp(-SUSP_DECAY * dtp), 4)
            e["last"] = now
        return e


def _resolve_actor(request, x_player):
    """Acteur : le handle X-Player s'il est fourni (rivals/multi-attaquant), sinon
    l'attaquant PRIMAIRE (console) — dont le cooldown reste porté par game_state."""
    if x_player and x_player.strip():
        return x_player.strip()[:32], False
    return "attaquant", True


def _actor_ip(request) -> str:
    xff = request.headers.get("x-forwarded-for", "") if request else ""
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if (request and request.client) else ""


def _actor_cooldown(actor: str, is_primary: bool) -> float:
    if is_primary:
        return _cooldown_remaining()
    e = _susp(actor)
    return max(0.0, round(e["blocked_until"] - time.time(), 1))


def _bump_suspicion(actor: str, delta: float, ip: str = "", reason: str = ""):
    """Monte la suspicion (atténuée par la furtivité). Clampée [0,1]."""
    e = _susp(actor)
    with susp_lock:
        e["score"] = round(min(1.0, max(0.0, e["score"] + delta * _stealth_factor())), 4)
        e["last"] = time.time()
        if ip:
            e["ip"] = ip
        if reason:
            e["last_reason"] = reason


def _block_prob(score: float) -> float:
    return min(1.0, (1.0 / (1.0 + math.exp(-SUSP_K * (score - SUSP_S0)))) * _proxy_factor())


def _maybe_block(actor: str, is_primary: bool, reason: str):
    """Tirage PROBABILISTE du blocage selon le score (isolation : seul cet acteur)."""
    e = _susp(actor)
    p = _block_prob(e["score"])
    if random.random() <= p:
        if is_primary:
            with game_lock:
                game_state["blocked_until"] = time.time() + SUSP_COOLDOWN
                game_state["block_reason"] = reason
            GAME_BLOCKED.set(1)
        else:
            with susp_lock:
                e["blocked_until"] = time.time() + SUSP_COOLDOWN
                e["last_reason"] = reason
        print(f"[GAME] IA BLOCK actor={actor} p={p:.2f} score={e['score']:.2f} — {reason}", flush=True)
        return True, round(p, 3)
    return False, round(p, 3)

game_state = {
    "victim": GAME_VICTIM,
    "loot": 0.0,              # butin courant détenu par l'attaquant (non neutralisé)
    "loot_neutralized": 0.0,  # butin repris par la défense (claw-back / intégrité)
    "exfiltrated_total": 0.0, # cumul exfiltré sur toute la partie (jamais remis à 0 sauf reset)
    "recon_count": 0,
    "heist_count": 0,
    "intel": [],              # infos révélées progressivement (fuite)
    "discovered": [],         # comptes clients découverts par la recon (sélecteur de cible)
    "blocked_until": 0.0,     # epoch ; > now => attaquant bloqué (cooldown)
    "block_reason": "",
    "heist_max": GAME_HEIST_MAX,
    "loot_cap": GAME_LOOT_CAP,
    "recon_needed": GAME_RECON_FOR_HEIST,
    "insider_count": 0,       # nb d'intel « insider » achetés au banquier (traçable IA)
    "dino_hijack": None,      # {"target": username} si un détournement Dino est armé
    "hk": {},                 # niveaux d'upgrades du shop hacker (stealth/proxy/toolkit/decoder)
    "client_heists": 0,       # vols de clients récents (fréquence -> difficulté croissante)
}
game_lock = threading.Lock()
degraded = {"on": False}  # bascule : endpoints métier en 503 (gated par GAME_DEGRADE)

# --- DISTRACTION : les ATTAQUES (flood) occupent l'IA -> détection affaiblie et
# vol possible/plus gros. Sans attaque en cours, l'IA analyse tout et bloque la
# recon/le vol. C'est le vrai but : affaiblir l'IA AVANT d'exfiltrer. ---
_req_times = deque(maxlen=6000)                 # horodatage des requêtes (fenêtre glissante)
DISTRACT_WINDOW = float(os.environ.get("DISTRACT_WINDOW", "8"))     # s
DISTRACT_BASELINE = float(os.environ.get("DISTRACT_BASELINE", "4")) # req/s "normales" (trafic légitime)
DISTRACT_SPAN = float(os.environ.get("DISTRACT_SPAN", "45"))        # req/s au-dessus = distraction max
DISTRACT_MIN = float(os.environ.get("DISTRACT_MIN", "0.25"))        # distraction mini pour agir


def _distraction() -> float:
    """0..1 : à quel point l'IA est distraite par la charge d'attaque en cours."""
    now = time.time()
    while _req_times and now - _req_times[0] > DISTRACT_WINDOW:
        _req_times.popleft()
    rate = len(_req_times) / DISTRACT_WINDOW
    return max(0.0, min(1.0, (rate - DISTRACT_BASELINE) / DISTRACT_SPAN))

GAME_RECON = Counter("game_recon_total", "Sondes de reconnaissance (jeu)")
GAME_HEIST = Counter("game_heist_total", "Tentatives de retrait réussies (jeu)")
GAME_HEIST_AMT = Counter("game_heist_amount_total", "Montant exfiltré cumulé (jeu)")
GAME_LOOT = Gauge("game_loot_current", "Butin courant détenu par l'attaquant (jeu)")
GAME_BLOCKED = Gauge("game_blocked", "1 si l'attaquant est bloqué par l'IA (jeu)")
GAME_INSIDER = Counter("game_insider_total", "Intel « insider » vendu par le banquier (jeu)")
GAME_DINO_HIJACK = Counter("game_dino_hijack_total", "Tentatives de détournement de gain Dino (jeu)", ["result"])
GAME_THEFT = Counter("game_theft_total", "Vols par type de cible et résultat (jeu)", ["target_type", "result"])
GAME_PHISH = Counter("game_phish_total", "Phishing (fausses enchères) par résultat (jeu)", ["result"])


def ha_event(label, kind="info"):
    """Trace un événement de bascule (visible dans le cockpit Haute-Dispo)."""
    t = dt.datetime.now().strftime("%H:%M:%S")
    repl_state["events"].append({"t": t, "label": label, "kind": kind})
    repl_state["events"] = repl_state["events"][-40:]
    print(f"[ha] {label}", flush=True)

# --- WAF applicatif (signatures type OWASP) ---
WAF_BLOCKED = Counter("waf_blocked_total", "Requêtes bloquées par le WAF applicatif", ["rule"])
WAF_PATTERNS = [
    ("sqli_or_and", re.compile(r"(?i)('|%27)\s*(or|and)\s")),
    ("sqli_union", re.compile(r"(?i)\bunion\b.*\bselect\b")),
    ("sqli_tautology", re.compile(r"(?i)\bor\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+")),
    ("sqli_drop", re.compile(r"(?i)\bdrop\b\s+\btable\b")),
    ("sql_comment", re.compile(r"(--|#|/\*)")),
    ("xss_script", re.compile(r"(?i)<script")),
]


def waf_scan(source: str, **fields):
    for name, value in fields.items():
        if not isinstance(value, str):
            continue
        for rule, rx in WAF_PATTERNS:
            if rx.search(value):
                WAF_BLOCKED.labels(rule=rule).inc()
                print(f"[WAF] BLOCK rule={rule} source={source} field={name} value={value!r}", flush=True)
                raise HTTPException(403, "requête bloquée par le WAF")


def guard_degraded():
    """Bascule : si le principal est en mode dégradé (compromission), les endpoints
    métier répondent 503 -> nginx (proxy_next_upstream) bascule vers le secours."""
    if degraded["on"]:
        raise HTTPException(503, "noeud en mode dégradé — bascule secours en cours")


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="client")  # client | banker


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    balance: Mapped[float] = mapped_column(Numeric(14, 2))
    savings: Mapped[float] = mapped_column(Numeric(14, 2), default=0)   # livret d'epargne
    currency: Mapped[str] = mapped_column(String(3))


class Favorite(Base):
    __tablename__ = "favorites"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    fav_username: Mapped[str] = mapped_column(String(64))


class Livret(Base):
    """Livret d'épargne SUPPLÉMENTAIRE (le livret principal reste accounts.savings).
    Chaque livret produit des intérêts à son propre taux (jeu idle)."""
    __tablename__ = "livrets"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(40), default="Livret")
    balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    rate: Mapped[float] = mapped_column(Numeric(6, 4), default=0)   # taux par cycle propre
    level: Mapped[int] = mapped_column(Integer, default=1)


class Upgrade(Base):
    """Niveau d'une amélioration achetée au shop (par utilisateur, par clé)."""
    __tablename__ = "upgrades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    ukey: Mapped[str] = mapped_column(String(32))
    level: Mapped[int] = mapped_column(Integer, default=0)


class Transaction(Base):
    __tablename__ = "transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    type: Mapped[str] = mapped_column(String(16))
    recipient: Mapped[str] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    idem_key: Mapped[str] = mapped_column(String(64), nullable=True)  # clé d'idempotence (reprise)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Mail(Base):
    """Boîte mail in-app (annonces banque, lots, enchères, phishing plus tard)."""
    __tablename__ = "mail"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    subject: Mapped[str] = mapped_column(String(140))
    body: Mapped[str] = mapped_column(String(2000), default="")
    kind: Mapped[str] = mapped_column(String(16), default="info")  # info|auction|quiz|prize|phishing
    is_read: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Auction(Base):
    """Enchère officielle créée par le banquier. À la clôture, le plus offrant est
    débité de sa mise et crédité de la VALEUR de l'objet (gain net = valeur - mise)."""
    __tablename__ = "auctions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(140))
    item_value: Mapped[float] = mapped_column(Numeric(14, 2))
    min_bid: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|closed
    created_by: Mapped[str] = mapped_column(String(64))
    winner: Mapped[str] = mapped_column(String(64), nullable=True)
    winning_bid: Mapped[float] = mapped_column(Numeric(14, 2), nullable=True)
    phish: Mapped[int] = mapped_column(Integer, default=0)            # P5 : fausse enchère (phishing)
    beneficiary: Mapped[str] = mapped_column(String(64), nullable=True)  # attaquant qui empoche la mise
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Bid(Base):
    __tablename__ = "bids"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    auction_id: Mapped[int] = mapped_column(ForeignKey("auctions.id", ondelete="CASCADE"))
    username: Mapped[str] = mapped_column(String(64))
    amount: Mapped[float] = mapped_column(Numeric(14, 2))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class Quiz(Base):
    """Quiz du banquier : 1re bonne réponse gagne le lot (crédité, banquier-funded)."""
    __tablename__ = "quizzes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(500))
    answer: Mapped[str] = mapped_column(String(140))
    prize: Mapped[float] = mapped_column(Numeric(14, 2))
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|closed
    winner: Mapped[str] = mapped_column(String(64), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class ChatRoom(Base):
    """Salon de discussion : 'global' (ouvert à tous) ou 'private' (membres choisis)."""
    __tablename__ = "chat_rooms"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(12), default="private")  # global|private
    owner: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class ChatMember(Base):
    __tablename__ = "chat_members"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"))
    member: Mapped[str] = mapped_column(String(64))


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    room_id: Mapped[int] = mapped_column(ForeignKey("chat_rooms.id", ondelete="CASCADE"))
    author: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(String(1000))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


class IntelOffer(Base):
    """P2.6 — offre d'intel « insider » : le banquier vend des infos sur un client
    à un attaquant (payé avec le butin). L'achat débloque la recon côté /game."""
    __tablename__ = "intel_offers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    target: Mapped[str] = mapped_column(String(64))
    price: Mapped[float] = mapped_column(Numeric(14, 2))
    created_by: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(12), default="open")  # open|sold
    buyer: Mapped[str] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now())


_engine = None


def engine():
    global _engine
    if _engine is None:
        _engine = create_engine(DATABASE_URL, pool_pre_ping=True)
    return _engine


def wait_for_db(retries: int = 30, delay: float = 2.0):
    last = None
    for _ in range(retries):
        try:
            with engine().connect():
                return
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(delay)
    raise RuntimeError(f"DB unreachable: {last}")


def current_claims(authorization: str = Header(default=None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "invalid token")


def current_user(claims: dict = Depends(current_claims)) -> str:
    return claims["sub"]


def require_banker(claims: dict = Depends(current_claims)) -> str:
    """Autorise uniquement un jeton de rôle 'banker' (interface banquier)."""
    if claims.get("role") != "banker":
        raise HTTPException(403, "réservé au compte banquier")
    return claims["sub"]


app = FastAPI(title="Resilience-Alpha — Payment API")


@app.middleware("http")
async def _track_load(request, call_next):
    """Compte la charge entrante (pour calculer la distraction de l'IA)."""
    try:
        _req_times.append(time.time())
    except Exception:  # noqa: BLE001
        pass
    return await call_next(request)


# ---------------- Temps réel (WebSocket) ----------------
class WSManager:
    """Diffuse les événements de transaction aux clients connectés (live, sans refresh)."""
    def __init__(self):
        self.active = set()
        self.loop = None

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws):
        self.active.discard(ws)

    async def _broadcast(self, msg: str):
        for ws in list(self.active):
            try:
                await ws.send_text(msg)
            except Exception:  # noqa: BLE001
                self.active.discard(ws)

    def publish(self, event: dict):
        """Appelable depuis un thread sync (handler HTTP) : planifie la diffusion."""
        if self.loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._broadcast(json.dumps(event)), self.loop)
        except Exception:  # noqa: BLE001
            pass


ws_manager = WSManager()


@app.on_event("startup")
async def _capture_loop():
    ws_manager.loop = asyncio.get_running_loop()


@app.websocket("/ws")
async def ws_events(ws: WebSocket):
    await ws_manager.connect(ws)
    try:
        while True:
            await ws.receive_text()  # garde la connexion ouverte (ping/keepalive)
    except WebSocketDisconnect:
        ws_manager.disconnect(ws)
    except Exception:  # noqa: BLE001
        ws_manager.disconnect(ws)


class TxIn(BaseModel):
    amount: float
    recipient: str | None = None           # username de l'ami à payer (ou marchand externe)
    idempotency_key: str | None = None     # pour reprendre une transaction sans double débit


@app.on_event("startup")
def startup():
    wait_for_db()
    # Migration légère : clé d'idempotence (compatible avec une base existante).
    with engine().begin() as c:
        c.execute(text("ALTER TABLE transactions ADD COLUMN IF NOT EXISTS idem_key VARCHAR(64)"))
        c.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ux_tx_idem ON transactions(idem_key) WHERE idem_key IS NOT NULL"))
        c.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(16) NOT NULL DEFAULT 'client'"))
        c.execute(text("ALTER TABLE accounts ADD COLUMN IF NOT EXISTS savings NUMERIC(14,2) NOT NULL DEFAULT 0"))
        c.execute(text("CREATE TABLE IF NOT EXISTS favorites ("
                       "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                       "fav_username VARCHAR(64) NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                       "UNIQUE(user_id, fav_username))"))
        c.execute(text("CREATE TABLE IF NOT EXISTS livrets ("
                       "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                       "name VARCHAR(40) NOT NULL DEFAULT 'Livret', balance NUMERIC(14,2) NOT NULL DEFAULT 0, "
                       "rate NUMERIC(6,4) NOT NULL DEFAULT 0, level INTEGER NOT NULL DEFAULT 1, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        c.execute(text("CREATE TABLE IF NOT EXISTS upgrades ("
                       "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                       "ukey VARCHAR(32) NOT NULL, level INTEGER NOT NULL DEFAULT 0, "
                       "UNIQUE(user_id, ukey))"))
        # P2 — boîte mail / enchères / quiz
        c.execute(text("CREATE TABLE IF NOT EXISTS mail ("
                       "id SERIAL PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, "
                       "subject VARCHAR(140) NOT NULL, body VARCHAR(2000) NOT NULL DEFAULT '', "
                       "kind VARCHAR(16) NOT NULL DEFAULT 'info', is_read INTEGER NOT NULL DEFAULT 0, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        c.execute(text("CREATE TABLE IF NOT EXISTS auctions ("
                       "id SERIAL PRIMARY KEY, title VARCHAR(140) NOT NULL, item_value NUMERIC(14,2) NOT NULL, "
                       "min_bid NUMERIC(14,2) NOT NULL DEFAULT 0, status VARCHAR(12) NOT NULL DEFAULT 'open', "
                       "created_by VARCHAR(64) NOT NULL, winner VARCHAR(64), winning_bid NUMERIC(14,2), "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        c.execute(text("CREATE TABLE IF NOT EXISTS bids ("
                       "id SERIAL PRIMARY KEY, auction_id INTEGER NOT NULL REFERENCES auctions(id) ON DELETE CASCADE, "
                       "username VARCHAR(64) NOT NULL, amount NUMERIC(14,2) NOT NULL, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        # P5 — phishing : fausses enchères (colonnes ajoutées à auctions)
        c.execute(text("ALTER TABLE auctions ADD COLUMN IF NOT EXISTS phish INTEGER NOT NULL DEFAULT 0"))
        c.execute(text("ALTER TABLE auctions ADD COLUMN IF NOT EXISTS beneficiary VARCHAR(64)"))
        c.execute(text("CREATE TABLE IF NOT EXISTS quizzes ("
                       "id SERIAL PRIMARY KEY, question VARCHAR(500) NOT NULL, answer VARCHAR(140) NOT NULL, "
                       "prize NUMERIC(14,2) NOT NULL, status VARCHAR(12) NOT NULL DEFAULT 'open', "
                       "winner VARCHAR(64), created_by VARCHAR(64) NOT NULL, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        # P2.5 — chat global + salons privés
        c.execute(text("CREATE TABLE IF NOT EXISTS chat_rooms ("
                       "id SERIAL PRIMARY KEY, name VARCHAR(64) NOT NULL, "
                       "kind VARCHAR(12) NOT NULL DEFAULT 'private', owner VARCHAR(64) NOT NULL, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        c.execute(text("CREATE TABLE IF NOT EXISTS chat_members ("
                       "id SERIAL PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE, "
                       "member VARCHAR(64) NOT NULL, UNIQUE(room_id, member))"))
        c.execute(text("CREATE TABLE IF NOT EXISTS chat_messages ("
                       "id SERIAL PRIMARY KEY, room_id INTEGER NOT NULL REFERENCES chat_rooms(id) ON DELETE CASCADE, "
                       "author VARCHAR(64) NOT NULL, body VARCHAR(1000) NOT NULL, "
                       "created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
        # P2.6 — offres d'intel « insider » (banquier -> attaquant)
        c.execute(text("CREATE TABLE IF NOT EXISTS intel_offers ("
                       "id SERIAL PRIMARY KEY, target VARCHAR(64) NOT NULL, price NUMERIC(14,2) NOT NULL, "
                       "created_by VARCHAR(64) NOT NULL, status VARCHAR(12) NOT NULL DEFAULT 'open', "
                       "buyer VARCHAR(64), created_at TIMESTAMPTZ NOT NULL DEFAULT now())"))
    # Compte BANQUE : le bot de trafic (trafficbot) est le coffre de la banque, pas un
    # joueur. On lui met le rôle 'bank' -> exclu du leaderboard/victoire/annuaire, mais
    # il reste une cible de hack très lucrative et très sécurisée (P3.5).
    if ROLE == "primary":
        try:
            with engine().begin() as c:
                c.execute(text("UPDATE users SET role='bank' WHERE username=:u AND role='client'"),
                          {"u": BANK_USER})
        except Exception:  # noqa: BLE001
            pass
    # Livret initial pour la cible du jeu (fuite « présence d'un livret » + vol épargne).
    if ROLE == "primary" and GAME_SEED_SAVINGS > 0:
        try:
            with Session(engine()) as s:
                vu = s.scalar(select(User).where(User.username == GAME_VICTIM))
                vacc = s.scalar(select(Account).where(Account.user_id == vu.id)) if vu else None
                if vacc is not None and float(vacc.savings) == 0:
                    vacc.savings = GAME_SEED_SAVINGS
                    s.commit()
        except Exception:  # noqa: BLE001
            pass
    # Salon global (ouvert à tous) : créé une seule fois.
    if ROLE == "primary":
        try:
            with Session(engine()) as s:
                if s.scalar(select(ChatRoom).where(ChatRoom.kind == "global")) is None:
                    s.add(ChatRoom(name="Global", kind="global", owner="system"))
                    s.commit()
        except Exception:  # noqa: BLE001
            pass
    if ROLE == "backup" and PEER_API_URL:
        threading.Thread(target=replicate_loop, daemon=True).start()
    threading.Thread(target=savings_interest_loop, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "api"}


@app.get("/accounts/me")
def my_account(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        if u is None:
            raise HTTPException(404, "user not found")
        acc = s.scalar(select(Account).where(Account.user_id == u.id))
        if acc is None:
            raise HTTPException(404, "account not found")
        return {"username": user, "balance": float(acc.balance), "savings": float(acc.savings),
                "savings_rate": savings_cfg["rate"], "savings_interval": savings_cfg["interval"],
                "currency": acc.currency}


@app.post("/transactions")
def create_transaction(body: TxIn, user: str = Depends(current_user)):
    guard_degraded()
    waf_scan("api/transactions", recipient=body.recipient or "")
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    key = body.idempotency_key
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        # Verrou de ligne (FOR UPDATE) : serialise les debits concurrents sur le meme
        # compte -> plus de solde negatif sous charge (attaque + canari + paiements).
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
        if acc is None:
            raise HTTPException(404, "account not found")

        # Reprise exactly-once : si la clé a déjà été traitée, on renvoie le résultat
        # SANS ré-appliquer (cas d'un ré-essai après bascule sur le backup).
        if key:
            prior = s.scalar(select(Transaction).where(Transaction.idem_key == key))
            if prior is not None:
                return {"id": prior.id, "status": prior.status, "amount": float(prior.amount),
                        "recipient": prior.recipient, "new_balance": float(acc.balance),
                        "resumed": True}

        # Destinataire : CLIENT connu -> transfert (crédit) ; marchand autorisé -> externe ;
        # sinon REFUS (pas de paiement vers un compte inexistant).
        rec_user = s.scalar(select(User).where(User.username == body.recipient)) if body.recipient else None
        if rec_user is not None and rec_user.id == u.id:
            raise HTTPException(400, "cannot pay yourself")
        if body.recipient and rec_user is None and body.recipient not in MERCHANTS:
            raise HTTPException(404, "destinataire introuvable")
        if rec_user is not None and (rec_user.role or "client") != "client":
            raise HTTPException(404, "destinataire introuvable")
        if float(acc.balance) < body.amount:
            raise HTTPException(402, "insufficient funds")

        acc.balance = float(acc.balance) - body.amount
        tx = Transaction(account_id=acc.id, amount=body.amount, type="debit",
                         recipient=body.recipient, status="completed", idem_key=key)
        s.add(tx)
        credited = False
        if rec_user is not None and (rec_user.role or "client") == "client":
            rec_acc = s.scalar(select(Account).where(Account.user_id == rec_user.id).with_for_update())
            if rec_acc is not None:
                rec_acc.balance = float(rec_acc.balance) + body.amount
                s.add(Transaction(account_id=rec_acc.id, amount=body.amount, type="credit",
                                  recipient=user, status="completed"))
                credited = True
        try:
            s.commit()
        except IntegrityError:
            # Course sur la clé d'idempotence : la transaction a déjà été appliquée.
            s.rollback()
            prior = s.scalar(select(Transaction).where(Transaction.idem_key == key))
            acc = s.scalar(select(Account).where(Account.user_id == u.id))
            if prior is not None:
                return {"id": prior.id, "status": prior.status, "amount": float(prior.amount),
                        "recipient": prior.recipient, "new_balance": float(acc.balance),
                        "resumed": True}
            raise
        ws_manager.publish({"type": "tx", "from": user, "to": body.recipient or "",
                            "amount": body.amount})
        return {"id": tx.id, "status": "completed", "amount": body.amount,
                "recipient": body.recipient, "credited": credited,
                "new_balance": float(acc.balance), "resumed": False}


@app.get("/users")
def list_users(q: str = "", user: str = Depends(current_user)):
    """Annuaire : clients enregistrés disponibles (recherche par nom)."""
    with Session(engine()) as s:
        stmt = select(User.username).where(User.username != user, User.role == "client")
        if q:
            stmt = stmt.where(User.username.ilike(f"%{q}%"))
        rows = s.scalars(stmt.order_by(User.username).limit(20)).all()
    return [{"username": r} for r in rows]


@app.get("/transactions")
def list_transactions(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        acc = s.scalar(select(Account).where(Account.user_id == u.id)) if u else None
        if acc is None:
            raise HTTPException(404, "account not found")
        rows = s.scalars(
            select(Transaction)
            .where(Transaction.account_id == acc.id)
            .order_by(Transaction.id.desc())
        ).all()
        return [
            {
                "id": r.id, "amount": float(r.amount), "type": r.type,
                "recipient": r.recipient, "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


# ---------------- Livret d'epargne ----------------
class SavingsOp(BaseModel):
    amount: float


@app.get("/savings")
def get_savings(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        acc = s.scalar(select(Account).where(Account.user_id == u.id)) if u else None
        if acc is None:
            raise HTTPException(404, "account not found")
        return {"balance": float(acc.balance), "savings": float(acc.savings),
                "rate": savings_cfg["rate"], "interval": savings_cfg["interval"]}


def _savings_move(user: str, amount: float, op: str):
    if amount <= 0:
        raise HTTPException(400, "le montant doit être positif")
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
        if acc is None:
            raise HTTPException(404, "account not found")
        if op == "deposit":
            if float(acc.balance) < amount:
                raise HTTPException(402, "solde courant insuffisant")
            acc.balance = float(acc.balance) - amount
            acc.savings = float(acc.savings) + amount
            s.add(Transaction(account_id=acc.id, amount=amount, type="debit",
                              recipient="LIVRET (dépôt)", status="completed"))
        else:  # withdraw
            if float(acc.savings) < amount:
                raise HTTPException(402, "épargne insuffisante")
            acc.savings = float(acc.savings) - amount
            acc.balance = float(acc.balance) + amount
            s.add(Transaction(account_id=acc.id, amount=amount, type="credit",
                              recipient="LIVRET (retrait)", status="completed"))
        s.commit()
        b, sv = float(acc.balance), float(acc.savings)
    ws_manager.publish({"type": "tx", "from": user, "to": "LIVRET", "amount": amount, "op": op})
    return {"status": "completed", "balance": b, "savings": sv}


@app.post("/savings/deposit")
def savings_deposit(body: SavingsOp, user: str = Depends(current_user)):
    return _savings_move(user, body.amount, "deposit")


@app.post("/savings/withdraw")
def savings_withdraw(body: SavingsOp, user: str = Depends(current_user)):
    return _savings_move(user, body.amount, "withdraw")


# -------- Livrets supplémentaires + fortune + leaderboard (jeu idle) --------
class LivretIn(BaseModel):
    name: str | None = None


class LivretOp(BaseModel):
    amount: float


def _user_or_404(s, user):
    u = s.scalar(select(User).where(User.username == user))
    if u is None:
        raise HTTPException(404, "user not found")
    return u


@app.get("/livrets")
def list_livrets(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id))
        extras = s.scalars(select(Livret).where(Livret.user_id == u.id).order_by(Livret.id)).all()
        p_level = _upg_level(s, u.id, "principal_rate")
        return {
            "principal": {"balance": float(acc.savings),
                          "rate": round(savings_cfg["rate"] + LIVRET_RATE_STEP * p_level, 4),
                          "level": p_level,
                          "upgrade_cost": _boost_cost(0, p_level),
                          "rate_step": LIVRET_RATE_STEP},
            # position = index+1 (le principal occupe la position 0)
            "livrets": [{"id": lv.id, "name": lv.name, "balance": float(lv.balance),
                         "rate": float(lv.rate), "level": lv.level,
                         "upgrade_cost": _boost_cost(idx + 1, lv.level),
                         "rate_step": LIVRET_RATE_STEP} for idx, lv in enumerate(extras)],
            "interval": savings_cfg["interval"],
        }


@app.post("/livrets")
def create_livret(body: LivretIn, user: str = Depends(current_user)):
    # Nombre de livrets autorisés = BASE + niveau de l'upgrade 'livret_slot' (acheté au shop).
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        n = int(s.scalar(select(func.count()).select_from(Livret).where(Livret.user_id == u.id)) or 0)
        allowed = BASE_LIVRET_SLOTS + _upg_level(s, u.id, "livret_slot")
        if n >= allowed:
            raise HTTPException(402, "achète un slot de livret au shop pour en ouvrir un de plus")
        name = (body.name or f"Livret {n + 2}")[:40]
        lv = Livret(user_id=u.id, name=name, balance=0, rate=savings_cfg["rate"], level=1)
        s.add(lv)
        s.commit()
        return {"id": lv.id, "name": lv.name, "balance": 0.0, "rate": float(lv.rate), "level": 1}


def _livret_move(user, livret_id, amount, op):
    if amount <= 0:
        raise HTTPException(400, "le montant doit être positif")
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        lv = s.scalar(select(Livret).where(Livret.id == livret_id,
                                           Livret.user_id == u.id).with_for_update())
        if acc is None or lv is None:
            raise HTTPException(404, "livret introuvable")
        if op == "deposit":
            if float(acc.balance) < amount:
                raise HTTPException(402, "solde courant insuffisant")
            acc.balance = float(acc.balance) - amount
            lv.balance = float(lv.balance) + amount
        else:
            if float(lv.balance) < amount:
                raise HTTPException(402, "livret insuffisant")
            lv.balance = float(lv.balance) - amount
            acc.balance = float(acc.balance) + amount
        s.commit()
        b, lb = float(acc.balance), float(lv.balance)
    ws_manager.publish({"type": "tx", "from": user, "to": "LIVRET", "amount": amount, "op": op})
    return {"status": "completed", "balance": b, "livret": lb}


@app.post("/livrets/{livret_id}/deposit")
def livret_deposit(livret_id: int, body: LivretOp, user: str = Depends(current_user)):
    return _livret_move(user, livret_id, body.amount, "deposit")


@app.post("/livrets/{livret_id}/withdraw")
def livret_withdraw(livret_id: int, body: LivretOp, user: str = Depends(current_user)):
    return _livret_move(user, livret_id, body.amount, "withdraw")


@app.get("/me/networth")
def my_networth(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id))
        lt = s.scalar(select(func.coalesce(func.sum(Livret.balance), 0)).where(Livret.user_id == u.id)) or 0
        nw = _networth_row(acc.balance, acc.savings, lt)
    return {"courant": float(acc.balance), "savings": float(acc.savings),
            "livrets_total": float(lt), "networth": nw, "target": WIN_TARGET,
            "won": nw >= WIN_TARGET, "progress": round(min(1.0, nw / WIN_TARGET), 4)}


@app.get("/leaderboard")
def leaderboard():
    with Session(engine()) as s:
        rows = s.execute(
            select(User.username, Account.balance, Account.savings,
                   func.coalesce(func.sum(Livret.balance), 0))
            .join(Account, Account.user_id == User.id)
            .outerjoin(Livret, Livret.user_id == User.id)
            .where(User.role == "client")
            .group_by(User.username, Account.balance, Account.savings)
        ).all()
    board = [{"name": r[0], "camp": "client", "networth": _networth_row(r[1], r[2], r[3])} for r in rows]
    board.append({"name": "attaquant", "camp": "attaquant", "networth": round(float(game_state.get("loot", 0)), 2)})
    board.sort(key=lambda x: x["networth"], reverse=True)
    return {"target": WIN_TARGET, "winner": game_winner if game_winner["name"] else None, "board": board[:20]}


# -------- Shop & upgrades (coûts exponentiels) --------
class BuyIn(BaseModel):
    ukey: str


@app.get("/shop")
def shop(user: str = Depends(current_user)):
    """Catalogue d'améliorations avec le niveau actuel et le PROCHAIN coût (par joueur)."""
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        items = []
        for ukey, cfg in SHOP.items():
            lvl = _upg_level(s, u.id, ukey)
            items.append({"ukey": ukey, "label": cfg["label"], "desc": cfg["desc"],
                          "level": lvl, "next_cost": upg_cost(cfg["base"], cfg["growth"], lvl)})
    return {"items": items}


@app.post("/shop/buy")
def shop_buy(body: BuyIn, user: str = Depends(current_user)):
    """Achat d'une amélioration : débite le compte courant (atomique), monte le niveau."""
    cfg = SHOP.get(body.ukey)
    if cfg is None:
        raise HTTPException(404, "amélioration inconnue")
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        upg = s.scalar(select(Upgrade).where(Upgrade.user_id == u.id,
                                             Upgrade.ukey == body.ukey).with_for_update())
        level = int(upg.level) if upg else 0
        cost = upg_cost(cfg["base"], cfg["growth"], level)
        if float(acc.balance) < cost:
            raise HTTPException(402, f"solde insuffisant (coût {cost} €)")
        acc.balance = float(acc.balance) - cost
        if upg is None:
            s.add(Upgrade(user_id=u.id, ukey=body.ukey, level=1))
        else:
            upg.level = level + 1
        s.commit()
        new_balance = float(acc.balance)
    ws_manager.publish({"type": "tx", "from": user, "to": "SHOP", "amount": cost, "op": "buy"})
    return {"status": "ok", "ukey": body.ukey, "level": level + 1, "paid": cost,
            "next_cost": upg_cost(cfg["base"], cfg["growth"], level + 1), "balance": new_balance}


@app.post("/livrets/{livret_id}/upgrade")
def livret_upgrade(livret_id: int, user: str = Depends(current_user)):
    """Booste le taux de production d'un livret (+LIVRET_RATE_STEP), coût exponentiel."""
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        lv = s.scalar(select(Livret).where(Livret.id == livret_id,
                                           Livret.user_id == u.id).with_for_update())
        if acc is None or lv is None:
            raise HTTPException(404, "livret introuvable")
        # position du livret (principal=0, extras 1,2,3… par ordre d'id)
        ids = s.scalars(select(Livret.id).where(Livret.user_id == u.id).order_by(Livret.id)).all()
        position = ids.index(livret_id) + 1
        cost = _boost_cost(position, lv.level)
        if float(acc.balance) < cost:
            raise HTTPException(402, f"solde insuffisant (coût {cost} €)")
        acc.balance = float(acc.balance) - cost
        lv.rate = round(float(lv.rate) + LIVRET_RATE_STEP, 4)
        lv.level = int(lv.level) + 1
        s.commit()
        out = {"id": lv.id, "level": lv.level, "rate": float(lv.rate), "paid": cost,
               "next_cost": _boost_cost(position, lv.level),
               "balance": float(acc.balance)}
    ws_manager.publish({"type": "tx", "from": user, "to": "SHOP", "amount": cost, "op": "upgrade"})
    return out


@app.post("/savings/upgrade")
def savings_upgrade(user: str = Depends(current_user)):
    """Booste le taux du LIVRET PRINCIPAL (+LIVRET_RATE_STEP), position 0.

    Le bonus est stocké dans l'upgrade 'principal_rate' et appliqué dans la
    boucle de production : taux effectif = savings_cfg['rate'] + step * niveau."""
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        if acc is None:
            raise HTTPException(404, "compte introuvable")
        upg = s.scalar(select(Upgrade).where(Upgrade.user_id == u.id,
                                             Upgrade.ukey == "principal_rate").with_for_update())
        level = int(upg.level) if upg else 0
        cost = _boost_cost(0, level)
        if float(acc.balance) < cost:
            raise HTTPException(402, f"solde insuffisant (coût {cost} €)")
        acc.balance = float(acc.balance) - cost
        if upg is None:
            upg = Upgrade(user_id=u.id, ukey="principal_rate", level=1)
            s.add(upg)
        else:
            upg.level = level + 1
        s.commit()
        new_level = int(upg.level)
        out = {"level": new_level,
               "rate": round(savings_cfg["rate"] + LIVRET_RATE_STEP * new_level, 4),
               "paid": cost, "next_cost": _boost_cost(0, new_level),
               "balance": float(acc.balance)}
    ws_manager.publish({"type": "tx", "from": user, "to": "SHOP", "amount": cost, "op": "upgrade"})
    return out


def _networth_row(balance, savings, livret_total):
    return round(float(balance) + float(savings) + float(livret_total), 2)


def _check_win():
    """Détecte le premier joueur (client OU attaquant) à atteindre WIN_TARGET.
    Fortune client = courant + livret principal + livrets ; attaquant = butin cumulé."""
    if game_winner["name"] is not None:
        return
    winner = None
    with Session(engine()) as s:
        rows = s.execute(
            select(User.username, Account.balance, Account.savings,
                   func.coalesce(func.sum(Livret.balance), 0))
            .join(Account, Account.user_id == User.id)
            .outerjoin(Livret, Livret.user_id == User.id)
            .where(User.role == "client")
            .group_by(User.username, Account.balance, Account.savings)
        ).all()
    for uname, bal, sav, lt in rows:
        nw = _networth_row(bal, sav, lt)
        if nw >= WIN_TARGET and (winner is None or nw > winner[1]):
            winner = (uname, nw, "client")
    # Attaquant : butin détenu
    try:
        loot = float(game_state.get("loot", 0))
        if loot >= WIN_TARGET and (winner is None or loot > winner[1]):
            winner = (game_state.get("victim") and "attaquant" or "attaquant", loot, "attaquant")
    except Exception:  # noqa: BLE001
        pass
    if winner:
        game_winner.update({"name": winner[0], "networth": winner[1],
                            "camp": winner[2], "at": time.time()})
        ws_manager.publish({"type": "win", "name": winner[0], "camp": winner[2], "networth": winner[1]})
        print(f"[GAME] VICTOIRE {winner[2]} {winner[0]} -> {winner[1]}", flush=True)


def savings_interest_loop():
    """Production idle toutes les N s (N = savings_cfg['interval']) sur le noeud
    autoritaire : intérêts sur le livret principal (accounts.savings, taux
    savings_cfg['rate']) ET sur chaque livret supplémentaire (à son propre taux).
    Pas de ligne d'historique par tick (sinon spam). Vérifie la victoire ensuite."""
    while True:
        time.sleep(max(1.0, float(savings_cfg["interval"])))
        rate = float(savings_cfg["rate"])
        if not repl_state.get("promoted"):
            continue
        try:
            touched = False
            with Session(engine()) as s:
                # Multiplicateur de production par utilisateur (upgrade 'global_mult').
                mults = {uid: _global_mult(lvl) for uid, lvl in s.execute(
                    select(Upgrade.user_id, Upgrade.level).where(Upgrade.ukey == "global_mult")).all()}
                # Boost du livret principal par utilisateur (upgrade 'principal_rate').
                p_levels = {uid: lvl for uid, lvl in s.execute(
                    select(Upgrade.user_id, Upgrade.level).where(Upgrade.ukey == "principal_rate")).all()}
                for a in s.scalars(select(Account).where(Account.savings > 0)).all():
                    eff_rate = rate + LIVRET_RATE_STEP * int(p_levels.get(a.user_id, 0))
                    if eff_rate <= 0:
                        continue
                    interest = round(float(a.savings) * eff_rate * mults.get(a.user_id, 1.0), 2)
                    if interest > 0:
                        a.savings = float(a.savings) + interest
                        touched = True
                for lv in s.scalars(select(Livret).where(Livret.balance > 0, Livret.rate > 0)).all():
                    interest = round(float(lv.balance) * float(lv.rate) * mults.get(lv.user_id, 1.0), 2)
                    if interest > 0:
                        lv.balance = float(lv.balance) + interest
                        touched = True
                s.commit()
            if touched:
                ws_manager.publish({"type": "tx", "from": "LIVRET", "to": "", "amount": 0, "op": "interest"})
            _check_win()
        except Exception:  # noqa: BLE001
            pass


# ---------------- Destinataires favoris ----------------
class FavIn(BaseModel):
    username: str


@app.get("/favorites")
def list_favorites(user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        rows = s.scalars(
            select(Favorite.fav_username).where(Favorite.user_id == u.id)
            .order_by(Favorite.fav_username)
        ).all() if u else []
    return [{"username": r} for r in rows]


@app.post("/favorites")
def add_favorite(body: FavIn, user: str = Depends(current_user)):
    waf_scan("api/favorites", username=body.username)
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        target = s.scalar(select(User).where(User.username == body.username))
        if target is None or (target.role or "client") != "client" or target.id == u.id:
            raise HTTPException(400, "destinataire invalide")
        exists = s.scalar(select(Favorite).where(
            Favorite.user_id == u.id, Favorite.fav_username == body.username))
        if exists is None:
            s.add(Favorite(user_id=u.id, fav_username=body.username))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
    return {"status": "ok", "username": body.username}


@app.delete("/favorites/{username}")
def del_favorite(username: str, user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        fav = s.scalar(select(Favorite).where(
            Favorite.user_id == u.id, Favorite.fav_username == username)) if u else None
        if fav is not None:
            s.delete(fav)
            s.commit()
    return {"status": "deleted", "username": username}


# ---------------- Casino (mini-jeux : dés, roulette, blackjack) ----------------
# Serveur autoritaire : RNG côté serveur, mise plafonnée, débit/crédit atomiques.
CASINO_MAX_BET = float(os.environ.get("CASINO_MAX_BET", "500"))
bj_games = {}          # username -> partie de blackjack en cours
bj_lock = threading.Lock()


class BetIn(BaseModel):
    bet: float
    choice: str | None = None     # dés: high|low|1..6 ; roulette: red|black|<numéro>


def _take_bet(s, user, bet):
    if not bet or bet <= 0:
        raise HTTPException(400, "mise invalide")
    if bet > CASINO_MAX_BET:
        raise HTTPException(400, f"mise maximale {CASINO_MAX_BET:.0f} €")
    u = s.scalar(select(User).where(User.username == user))
    acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
    if acc is None:
        raise HTTPException(404, "compte introuvable")
    if float(acc.balance) < bet:
        raise HTTPException(402, "solde insuffisant")
    acc.balance = float(acc.balance) - bet
    return acc


def _casino_settle(acc, bet, payout, game):
    s_add = acc  # account already loaded/locked by caller's session
    from sqlalchemy.orm import object_session
    sess = object_session(acc)
    sess.add(Transaction(account_id=acc.id, amount=bet, type="debit",
                         recipient=f"CASINO ({game})", status="completed"))
    if payout > 0:
        acc.balance = float(acc.balance) + payout
        sess.add(Transaction(account_id=acc.id, amount=payout, type="credit",
                             recipient=f"CASINO (gain {game})", status="completed"))


@app.post("/casino/dice")
def casino_dice(body: BetIn, user: str = Depends(current_user)):
    """Dés : mise sur haut (4-6), bas (1-3) → x2 ; ou un numéro exact → x6."""
    with Session(engine()) as s:
        acc = _take_bet(s, user, body.bet)
        roll = random.randint(1, 6)
        choice = (body.choice or "high").lower()
        payout = 0.0
        if choice in ("high", "haut") and roll >= 4:
            payout = body.bet * 2
        elif choice in ("low", "bas") and roll <= 3:
            payout = body.bet * 2
        elif choice.isdigit() and 1 <= int(choice) <= 6 and int(choice) == roll:
            payout = body.bet * 6
        _casino_settle(acc, body.bet, payout, "dés")
        s.commit()
        bal = float(acc.balance)
    ws_manager.publish({"type": "tx", "from": user, "to": "CASINO", "amount": body.bet, "op": "dice"})
    return {"roll": roll, "win": payout > 0, "payout": round(payout, 2), "balance": bal}


@app.post("/casino/roulette")
def casino_roulette(body: BetIn, user: str = Depends(current_user)):
    """Roulette (0-36) : rouge/noir → x2 ; pair/impair → x2 ; un numéro → x36."""
    REDS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
    with Session(engine()) as s:
        acc = _take_bet(s, user, body.bet)
        n = random.randint(0, 36)
        choice = (body.choice or "red").lower()
        payout = 0.0
        if choice in ("red", "rouge") and n in REDS:
            payout = body.bet * 2
        elif choice in ("black", "noir") and n != 0 and n not in REDS:
            payout = body.bet * 2
        elif choice in ("even", "pair") and n != 0 and n % 2 == 0:
            payout = body.bet * 2
        elif choice in ("odd", "impair") and n % 2 == 1:
            payout = body.bet * 2
        elif choice.isdigit() and 0 <= int(choice) <= 36 and int(choice) == n:
            payout = body.bet * 36
        _casino_settle(acc, body.bet, payout, "roulette")
        s.commit()
        bal = float(acc.balance)
    color = "vert" if n == 0 else ("rouge" if n in REDS else "noir")
    ws_manager.publish({"type": "tx", "from": user, "to": "CASINO", "amount": body.bet, "op": "roulette"})
    return {"number": n, "color": color, "win": payout > 0, "payout": round(payout, 2), "balance": bal}


def _bj_total(cards):
    total = sum(cards)
    aces = cards.count(11)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


def _draw():
    v = random.randint(1, 13)
    return 11 if v == 1 else min(10, v)   # as=11 (ajusté par _bj_total), figures=10


@app.post("/casino/blackjack/deal")
def bj_deal(body: BetIn, user: str = Depends(current_user)):
    """Blackjack : distribue (débite la mise). hit/stand ensuite."""
    with Session(engine()) as s:
        acc = _take_bet(s, user, body.bet)
        s.add(Transaction(account_id=acc.id, amount=body.bet, type="debit",
                          recipient="CASINO (blackjack)", status="completed"))
        s.commit()
        bal = float(acc.balance)
    player = [_draw(), _draw()]
    dealer = [_draw()]
    with bj_lock:
        bj_games[user] = {"player": player, "dealer": dealer, "bet": body.bet, "over": False}
    pt = _bj_total(player)
    if pt == 21:   # blackjack naturel : résolution immédiate
        return _bj_resolve(user)
    return {"player": player, "player_total": pt, "dealer": dealer, "dealer_total": _bj_total(dealer),
            "over": False, "balance": bal}


@app.post("/casino/blackjack/hit")
def bj_hit(user: str = Depends(current_user)):
    with bj_lock:
        g = bj_games.get(user)
        if not g or g["over"]:
            raise HTTPException(400, "aucune partie en cours")
        g["player"].append(_draw())
        pt = _bj_total(g["player"])
        bust = pt > 21
    if bust:
        return _bj_resolve(user)
    return {"player": g["player"], "player_total": pt, "dealer": g["dealer"],
            "dealer_total": _bj_total(g["dealer"]), "over": False}


@app.post("/casino/blackjack/stand")
def bj_stand(user: str = Depends(current_user)):
    return _bj_resolve(user, stand=True)


def _bj_resolve(user, stand=False):
    with bj_lock:
        g = bj_games.get(user)
        if not g:
            raise HTTPException(400, "aucune partie en cours")
        if stand or _bj_total(g["player"]) >= 21:
            while _bj_total(g["dealer"]) < 17:
                g["dealer"].append(_draw())
        pt, dt = _bj_total(g["player"]), _bj_total(g["dealer"])
        bet = g["bet"]
        if pt > 21:
            result, mult = "perdu", 0.0
        elif pt == 21 and len(g["player"]) == 2:
            result, mult = "blackjack", 2.5
        elif dt > 21 or pt > dt:
            result, mult = "gagné", 2.0
        elif pt == dt:
            result, mult = "égalité", 1.0
        else:
            result, mult = "perdu", 0.0
        g["over"] = True
        payout = round(bet * mult, 2)
    bal = None
    if payout > 0:
        with Session(engine()) as s:
            u = s.scalar(select(User).where(User.username == user))
            acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
            acc.balance = float(acc.balance) + payout
            s.add(Transaction(account_id=acc.id, amount=payout, type="credit",
                              recipient="CASINO (gain blackjack)", status="completed"))
            s.commit()
            bal = float(acc.balance)
    ws_manager.publish({"type": "tx", "from": user, "to": "CASINO", "amount": 0, "op": "blackjack"})
    return {"player": g["player"], "player_total": pt, "dealer": g["dealer"], "dealer_total": dt,
            "over": True, "result": result, "payout": payout, "balance": bal}


# ---------------- Interface banquier (rôle 'banker') ----------------
class BankOp(BaseModel):
    username: str                 # client visé
    amount: float                 # montant (> 0)
    note: str | None = None       # libellé optionnel (motif)


@app.get("/bank/accounts")
def bank_accounts(banker: str = Depends(require_banker)):
    """Tous les comptes clients avec leur solde (vue banquier)."""
    with Session(engine()) as s:
        rows = s.execute(
            select(User.username, Account.balance, Account.savings, Account.currency)
            .join(Account, Account.user_id == User.id)
            .where(User.role == "client")
            .order_by(User.username)
        ).all()
        total = sum(float(r.balance) + float(r.savings) for r in rows)
    return {
        "accounts": [
            {"username": r.username, "balance": float(r.balance),
             "savings": float(r.savings), "currency": r.currency}
            for r in rows
        ],
        "count": len(rows),
        "total_balance": round(total, 2),
    }


@app.get("/bank/transactions")
def bank_transactions(username: str = "", limit: int = 100, banker: str = Depends(require_banker)):
    """Historique global (ou filtré par client) — mouvements crédit/débit."""
    with Session(engine()) as s:
        stmt = (
            select(Transaction, User.username)
            .join(Account, Account.id == Transaction.account_id)
            .join(User, User.id == Account.user_id)
            .order_by(Transaction.id.desc())
        )
        if username:
            stmt = stmt.where(User.username == username)
        rows = s.execute(stmt.limit(max(1, min(limit, 500)))).all()
        return [
            {
                "id": t.id, "username": uname, "amount": float(t.amount), "type": t.type,
                "recipient": t.recipient, "status": t.status,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t, uname in rows
        ]


def _bank_apply(username: str, amount: float, op: str, note: str | None, banker: str):
    """Crédit (dépôt) ou débit (retrait) banquier sur le compte d'un client."""
    waf_scan("api/bank", username=username, note=note or "")
    if amount <= 0:
        raise HTTPException(400, "le montant doit être positif")
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == username))
        if u is None or (u.role or "client") == "banker":
            raise HTTPException(404, "client introuvable")
        acc = s.scalar(select(Account).where(Account.user_id == u.id))
        if acc is None:
            raise HTTPException(404, "compte introuvable")
        if op == "debit" and float(acc.balance) < amount:
            raise HTTPException(402, "solde insuffisant")
        label = note or ("BANQUE (dépôt)" if op == "credit" else "BANQUE (retrait)")
        acc.balance = float(acc.balance) + (amount if op == "credit" else -amount)
        s.add(Transaction(account_id=acc.id, amount=amount, type=op,
                          recipient=label, status="completed"))
        s.commit()
        new_balance = float(acc.balance)
    # Temps réel : prévient tous les écrans (client concerné + dashboard banquier).
    ws_manager.publish({"type": "tx", "from": banker if op == "debit" else "BANQUE",
                        "to": username, "amount": amount, "op": op})
    return {"status": "completed", "username": username, "op": op,
            "amount": amount, "new_balance": new_balance}


@app.post("/bank/credit")
def bank_credit(body: BankOp, banker: str = Depends(require_banker)):
    return _bank_apply(body.username, body.amount, "credit", body.note, banker)


@app.post("/bank/debit")
def bank_debit(body: BankOp, banker: str = Depends(require_banker)):
    return _bank_apply(body.username, body.amount, "debit", body.note, banker)


class SavingsCfgIn(BaseModel):
    rate: float | None = None       # taux par cycle (ex. 0.01 = 1%)
    interval: float | None = None   # secondes entre deux versements d'intérêts


@app.get("/bank/savings-config")
def bank_savings_config(banker: str = Depends(require_banker)):
    """Config du livret (taux + intervalle), pilotée par le banquier."""
    return {"rate": savings_cfg["rate"], "interval": savings_cfg["interval"],
            "rate_pct": round(savings_cfg["rate"] * 100, 3)}


@app.post("/bank/savings-config")
def bank_set_savings_config(body: SavingsCfgIn, banker: str = Depends(require_banker)):
    """Règle EN DIRECT le taux et/ou l'intervalle du livret (bornes raisonnables)."""
    if body.rate is not None:
        if not (0 <= body.rate <= 0.5):
            raise HTTPException(400, "taux hors bornes (0 à 0.5, soit 0–50% par cycle)")
        savings_cfg["rate"] = round(float(body.rate), 4)
    if body.interval is not None:
        if not (5 <= body.interval <= 3600):
            raise HTTPException(400, "intervalle hors bornes (5 à 3600 s)")
        savings_cfg["interval"] = float(body.interval)
    ws_manager.publish({"type": "tx", "from": "LIVRET", "to": "", "amount": 0, "op": "config"})
    return {"rate": savings_cfg["rate"], "interval": savings_cfg["interval"],
            "rate_pct": round(savings_cfg["rate"] * 100, 3)}


# ---------------- P2 : boîte mail / enchères / quiz ----------------
def _mail_clients(s, subject, body, kind="info"):
    """Insère un mail pour TOUS les clients (annonce banque). À appeler dans une
    session ouverte, avant commit."""
    for uid in s.scalars(select(User.id).where(User.role == "client")).all():
        s.add(Mail(user_id=uid, subject=subject[:140], body=body[:2000], kind=kind))


@app.get("/mail")
def list_mail(user: str = Depends(current_user)):
    """Boîte mail du joueur (annonces, lots gagnés…)."""
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        rows = s.scalars(select(Mail).where(Mail.user_id == u.id)
                         .order_by(Mail.id.desc()).limit(50)).all()
        unread = int(s.scalar(select(func.count()).select_from(Mail)
                              .where(Mail.user_id == u.id, Mail.is_read == 0)) or 0)
    return {"unread": unread, "mail": [
        {"id": m.id, "subject": m.subject, "body": m.body, "kind": m.kind,
         "read": bool(m.is_read),
         "created_at": m.created_at.isoformat() if m.created_at else None} for m in rows]}


@app.post("/mail/{mail_id}/read")
def read_mail(mail_id: int, user: str = Depends(current_user)):
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        m = s.scalar(select(Mail).where(Mail.id == mail_id, Mail.user_id == u.id))
        if m is None:
            raise HTTPException(404, "message introuvable")
        m.is_read = 1
        s.commit()
    return {"ok": True, "id": mail_id}


class AuctionIn(BaseModel):
    title: str
    item_value: float
    min_bid: float | None = 0


class BidIn(BaseModel):
    amount: float


@app.post("/bank/auctions")
def bank_create_auction(body: AuctionIn, banker: str = Depends(require_banker)):
    if body.item_value <= 0:
        raise HTTPException(400, "valeur de l'objet invalide")
    with Session(engine()) as s:
        a = Auction(title=(body.title or "Objet").strip()[:140], item_value=round(float(body.item_value), 2),
                    min_bid=round(max(0.0, float(body.min_bid or 0)), 2), status="open", created_by=banker)
        s.add(a)
        s.flush()
        _mail_clients(s, f"Nouvelle enchère : {a.title}",
                      f"La banque met en vente « {a.title} » (valeur estimée {float(a.item_value):.0f} €). "
                      f"Mise minimale {float(a.min_bid):.0f} €. Enchérissez depuis l'onglet Enchères !", "auction")
        aid = a.id
        s.commit()
    ws_manager.publish({"type": "auction", "op": "open", "id": aid})
    ws_manager.publish({"type": "mail"})
    return {"id": aid, "status": "open"}


@app.get("/auctions")
def list_auctions(user: str = Depends(current_user)):
    """Enchères visibles par les joueurs (plus haute mise + ma mise, pas les noms)."""
    with Session(engine()) as s:
        auctions = s.scalars(select(Auction).order_by(Auction.id.desc()).limit(30)).all()
        out = []
        for a in auctions:
            top = s.execute(select(func.max(Bid.amount)).where(Bid.auction_id == a.id)).scalar()
            mine = s.execute(select(func.max(Bid.amount)).where(
                Bid.auction_id == a.id, Bid.username == user)).scalar()
            out.append({"id": a.id, "title": a.title, "item_value": float(a.item_value),
                        "min_bid": float(a.min_bid), "status": a.status,
                        "highest_bid": float(top) if top is not None else None,
                        "my_bid": float(mine) if mine is not None else None,
                        "winner": a.winner,
                        "winning_bid": float(a.winning_bid) if a.winning_bid is not None else None})
    return {"auctions": out}


@app.post("/auctions/{auction_id}/bid")
def place_bid(auction_id: int, body: BidIn, user: str = Depends(current_user)):
    amt = round(float(body.amount), 2)
    if amt <= 0:
        raise HTTPException(400, "mise invalide")
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        if (u.role or "client") != "client":
            raise HTTPException(403, "seuls les clients peuvent enchérir")
        a = s.scalar(select(Auction).where(Auction.id == auction_id))
        if a is None or a.status != "open":
            raise HTTPException(404, "enchère close ou introuvable")
        acc = s.scalar(select(Account).where(Account.user_id == u.id))
        if acc is None or float(acc.balance) < amt:
            raise HTTPException(402, "solde insuffisant pour couvrir la mise")
        top = s.execute(select(func.max(Bid.amount)).where(Bid.auction_id == a.id)).scalar()
        floor = max(float(a.min_bid), float(top) if top is not None else 0.0)
        if amt <= floor:
            raise HTTPException(400, f"la mise doit dépasser {floor:.0f} €")
        s.add(Bid(auction_id=a.id, username=user, amount=amt))
        s.commit()
    ws_manager.publish({"type": "auction", "op": "bid", "id": auction_id, "amount": amt})
    return {"ok": True, "auction_id": auction_id, "amount": amt}


@app.post("/bank/auctions/{auction_id}/close")
def bank_close_auction(auction_id: int, banker: str = Depends(require_banker)):
    """Clôture : le plus offrant SOLVABLE est débité de sa mise et crédité de la
    valeur de l'objet (gain net = valeur - mise). Mail au gagnant."""
    winner = None
    winning_bid = None
    with Session(engine()) as s:
        a = s.scalar(select(Auction).where(Auction.id == auction_id).with_for_update())
        if a is None:
            raise HTTPException(404, "enchère introuvable")
        if a.phish:
            raise HTTPException(400, "enchère non officielle (signalée frauduleuse) — non clôturable ici")
        if a.status == "closed":
            raise HTTPException(400, "enchère déjà close")
        bids = s.scalars(select(Bid).where(Bid.auction_id == a.id)
                         .order_by(Bid.amount.desc(), Bid.id.asc())).all()
        val = float(a.item_value)
        for b in bids:
            wu = s.scalar(select(User).where(User.username == b.username))
            if wu is None or (wu.role or "client") != "client":
                continue
            wacc = s.scalar(select(Account).where(Account.user_id == wu.id).with_for_update())
            bid_amt = float(b.amount)
            if wacc is None or float(wacc.balance) < bid_amt:
                continue  # ne peut plus payer sa mise -> offrant suivant
            wacc.balance = float(wacc.balance) - bid_amt + val
            s.add(Transaction(account_id=wacc.id, amount=bid_amt, type="debit",
                              recipient=f"ENCHÈRE « {a.title} » (mise)", status="completed"))
            s.add(Transaction(account_id=wacc.id, amount=val, type="credit",
                              recipient=f"ENCHÈRE « {a.title} » (objet)", status="completed"))
            net = round(val - bid_amt, 2)
            s.add(Mail(user_id=wu.id, subject=f"Enchère remportée : {a.title}",
                       body=f"Félicitations ! Vous remportez « {a.title} » pour une mise de {bid_amt:.0f} €. "
                            f"Objet crédité {val:.0f} € — gain net {net:+.0f} €.", kind="prize"))
            winner = b.username
            winning_bid = bid_amt
            break
        a.status = "closed"
        a.winner = winner
        a.winning_bid = winning_bid
        s.commit()
    ws_manager.publish({"type": "auction", "op": "close", "id": auction_id, "winner": winner})
    ws_manager.publish({"type": "mail"})
    _check_win()
    return {"ok": True, "winner": winner, "winning_bid": winning_bid}


@app.get("/bank/auctions")
def bank_list_auctions(banker: str = Depends(require_banker)):
    """Vue banquier : enchères + mises (noms visibles)."""
    with Session(engine()) as s:
        auctions = s.scalars(select(Auction).order_by(Auction.id.desc()).limit(30)).all()
        out = []
        for a in auctions:
            bids = s.scalars(select(Bid).where(Bid.auction_id == a.id)
                             .order_by(Bid.amount.desc()).limit(10)).all()
            out.append({"id": a.id, "title": a.title, "item_value": float(a.item_value),
                        "min_bid": float(a.min_bid), "status": a.status, "winner": a.winner,
                        "winning_bid": float(a.winning_bid) if a.winning_bid is not None else None,
                        "phish": bool(a.phish), "beneficiary": a.beneficiary,
                        "bids": [{"username": b.username, "amount": float(b.amount)} for b in bids]})
    return {"auctions": out}


class QuizIn(BaseModel):
    question: str
    answer: str
    prize: float


class AnswerIn(BaseModel):
    answer: str


@app.post("/bank/quizzes")
def bank_create_quiz(body: QuizIn, banker: str = Depends(require_banker)):
    if body.prize <= 0:
        raise HTTPException(400, "lot invalide")
    if not (body.answer or "").strip():
        raise HTTPException(400, "réponse vide")
    with Session(engine()) as s:
        q = Quiz(question=(body.question or "").strip()[:500], answer=body.answer.strip()[:140],
                 prize=round(float(body.prize), 2), status="open", created_by=banker)
        s.add(q)
        s.flush()
        _mail_clients(s, "Quiz de la banque !",
                      f"Question : {q.question}\nLot : {float(q.prize):.0f} € pour la 1re bonne réponse. "
                      f"Répondez vite depuis l'onglet Quiz !", "quiz")
        qid = q.id
        s.commit()
    ws_manager.publish({"type": "quiz", "op": "open", "id": qid})
    ws_manager.publish({"type": "mail"})
    return {"id": qid, "status": "open"}


@app.get("/quizzes")
def list_quizzes(user: str = Depends(current_user)):
    """Quiz visibles par les joueurs (sans la réponse)."""
    with Session(engine()) as s:
        rows = s.scalars(select(Quiz).order_by(Quiz.id.desc()).limit(20)).all()
    return {"quizzes": [{"id": q.id, "question": q.question, "prize": float(q.prize),
                         "status": q.status, "winner": q.winner} for q in rows]}


@app.post("/quizzes/{quiz_id}/answer")
def answer_quiz(quiz_id: int, body: AnswerIn, user: str = Depends(current_user)):
    """1re bonne réponse : lot crédité (banquier-funded), quiz fermé."""
    guess = (body.answer or "").strip().lower()
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        if (u.role or "client") != "client":
            raise HTTPException(403, "seuls les clients peuvent répondre")
        q = s.scalar(select(Quiz).where(Quiz.id == quiz_id).with_for_update())
        if q is None or q.status != "open":
            raise HTTPException(404, "quiz clos ou introuvable")
        if guess != (q.answer or "").strip().lower():
            return {"ok": False, "correct": False}
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        prize = float(q.prize)
        acc.balance = float(acc.balance) + prize
        s.add(Transaction(account_id=acc.id, amount=prize, type="credit",
                          recipient="QUIZ (lot)", status="completed"))
        q.status = "closed"
        q.winner = user
        s.add(Mail(user_id=u.id, subject="Quiz gagné !",
                   body=f"Bonne réponse ! Vous gagnez {prize:.0f} €.", kind="prize"))
        s.commit()
        new_balance = float(acc.balance)
    ws_manager.publish({"type": "quiz", "op": "win", "id": quiz_id, "winner": user})
    ws_manager.publish({"type": "tx", "from": "QUIZ", "to": user, "amount": prize})
    ws_manager.publish({"type": "mail"})
    _check_win()
    return {"ok": True, "correct": True, "prize": prize, "balance": new_balance}


@app.get("/bank/quizzes")
def bank_list_quizzes(banker: str = Depends(require_banker)):
    """Vue banquier : quiz avec la réponse."""
    with Session(engine()) as s:
        rows = s.scalars(select(Quiz).order_by(Quiz.id.desc()).limit(20)).all()
    return {"quizzes": [{"id": q.id, "question": q.question, "answer": q.answer,
                         "prize": float(q.prize), "status": q.status, "winner": q.winner} for q in rows]}


# ---------------- P2.5 : chat global + salons privés ----------------
def chat_identity(authorization: str = Header(default=None),
                  x_player: str = Header(default=None)) -> tuple:
    """Identité pour le chat. JWT -> (username, role). Sinon invité (attaquant/
    anonyme) via l'en-tête X-Player, à condition de NE PAS usurper un compte existant."""
    if authorization and authorization.startswith("Bearer "):
        try:
            claims = jwt.decode(authorization.split(" ", 1)[1], JWT_SECRET, algorithms=[JWT_ALG])
            return claims["sub"], claims.get("role", "client")
        except Exception:  # noqa: BLE001
            raise HTTPException(401, "invalid token")
    name = (x_player or "").strip()[:32]
    if not name:
        raise HTTPException(401, "identité requise (connexion ou en-tête X-Player)")
    with Session(engine()) as s:
        if s.scalar(select(User).where(User.username == name)) is not None:
            raise HTTPException(403, "ce pseudo correspond à un compte — connecte-toi")
    return name, "invité"


def _room_access(s, room: ChatRoom, me: str) -> bool:
    if room is None:
        return False
    if room.kind == "global":
        return True
    if room.owner == me:
        return True
    return s.scalar(select(ChatMember).where(
        ChatMember.room_id == room.id, ChatMember.member == me)) is not None


class RoomIn(BaseModel):
    name: str
    members: list[str] | None = None


class MemberIn(BaseModel):
    member: str


class MsgIn(BaseModel):
    body: str


@app.get("/chat/rooms")
def chat_rooms(ident: tuple = Depends(chat_identity)):
    """Salons visibles : le global + les salons privés dont je suis membre/propriétaire."""
    me, _role = ident
    with Session(engine()) as s:
        rooms = s.scalars(select(ChatRoom).order_by(ChatRoom.id)).all()
        out = []
        for r in rooms:
            if not _room_access(s, r, me):
                continue
            members = []
            if r.kind != "global":
                members = s.scalars(select(ChatMember.member).where(
                    ChatMember.room_id == r.id).order_by(ChatMember.member)).all()
            out.append({"id": r.id, "name": r.name, "kind": r.kind, "owner": r.owner,
                        "members": list(members)})
    return {"me": me, "rooms": out}


@app.post("/chat/rooms")
def chat_create_room(body: RoomIn, ident: tuple = Depends(chat_identity)):
    """Crée un salon privé (le créateur en est membre) et ajoute les membres voulus."""
    me, _role = ident
    name = (body.name or "Salon").strip()[:64]
    with Session(engine()) as s:
        r = ChatRoom(name=name, kind="private", owner=me)
        s.add(r)
        s.flush()
        wanted = set([me] + [m.strip()[:64] for m in (body.members or []) if m and m.strip()])
        for m in wanted:
            s.add(ChatMember(room_id=r.id, member=m))
        rid = r.id
        s.commit()
    ws_manager.publish({"type": "chat", "op": "room", "id": rid})
    return {"id": rid, "name": name, "kind": "private", "owner": me, "members": sorted(wanted)}


@app.post("/chat/rooms/{room_id}/members")
def chat_add_member(room_id: int, body: MemberIn, ident: tuple = Depends(chat_identity)):
    """Ajoute un membre à un salon privé (propriétaire uniquement)."""
    me, _role = ident
    member = (body.member or "").strip()[:64]
    if not member:
        raise HTTPException(400, "membre invalide")
    with Session(engine()) as s:
        r = s.scalar(select(ChatRoom).where(ChatRoom.id == room_id))
        if r is None or r.kind == "global":
            raise HTTPException(404, "salon privé introuvable")
        if r.owner != me:
            raise HTTPException(403, "seul le propriétaire du salon peut ajouter des membres")
        exists = s.scalar(select(ChatMember).where(
            ChatMember.room_id == r.id, ChatMember.member == member))
        if exists is None:
            s.add(ChatMember(room_id=r.id, member=member))
            try:
                s.commit()
            except IntegrityError:
                s.rollback()
    ws_manager.publish({"type": "chat", "op": "member", "id": room_id})
    return {"ok": True, "room_id": room_id, "member": member}


@app.get("/chat/rooms/{room_id}/messages")
def chat_messages(room_id: int, after: int = 0, ident: tuple = Depends(chat_identity)):
    """Messages d'un salon (contrôle d'accès). `after` pour un polling incrémental."""
    me, _role = ident
    with Session(engine()) as s:
        r = s.scalar(select(ChatRoom).where(ChatRoom.id == room_id))
        if not _room_access(s, r, me):
            raise HTTPException(403, "accès refusé à ce salon")
        rows = s.scalars(select(ChatMessage).where(
            ChatMessage.room_id == room_id, ChatMessage.id > after)
            .order_by(ChatMessage.id).limit(200)).all()
        return {"room_id": room_id, "kind": r.kind, "messages": [
            {"id": m.id, "author": m.author, "body": m.body,
             "created_at": m.created_at.isoformat() if m.created_at else None} for m in rows]}


@app.post("/chat/rooms/{room_id}/messages")
def chat_post(room_id: int, body: MsgIn, ident: tuple = Depends(chat_identity)):
    """Poste un message (contrôle d'accès). Diffusion WS live ; pour un salon privé
    on ne diffuse PAS le contenu (juste une notification) — les écrans refetchent."""
    me, _role = ident
    txt = (body.body or "").strip()[:1000]
    if not txt:
        raise HTTPException(400, "message vide")
    with Session(engine()) as s:
        r = s.scalar(select(ChatRoom).where(ChatRoom.id == room_id))
        if not _room_access(s, r, me):
            raise HTTPException(403, "accès refusé à ce salon")
        m = ChatMessage(room_id=room_id, author=me, body=txt)
        s.add(m)
        s.commit()
        mid = m.id
        kind = r.kind
    evt = {"type": "chat", "op": "msg", "room": room_id, "kind": kind, "id": mid}
    if kind == "global":
        evt.update({"author": me, "body": txt})
    ws_manager.publish(evt)
    return {"ok": True, "id": mid, "room_id": room_id, "author": me, "body": txt}


# ---------------- P2.6 : banquier insider (vente d'intel) ----------------
class IntelOfferIn(BaseModel):
    target: str
    price: float


@app.post("/bank/intel/offer")
def bank_intel_offer(body: IntelOfferIn, banker: str = Depends(require_banker)):
    """Le banquier met en vente de l'intel sur un client (insider, payé au butin)."""
    target = (body.target or "").strip()
    if body.price < 0:
        raise HTTPException(400, "prix invalide")
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == target))
        if u is None or (u.role or "client") != "client":
            raise HTTPException(400, "cible invalide — un client existant est requis")
        o = IntelOffer(target=target, price=round(float(body.price), 2),
                       created_by=banker, status="open")
        s.add(o)
        s.flush()
        oid = o.id
        s.commit()
    print(f"[GAME] INSIDER offer banker={banker} target={target} price={body.price}", flush=True)
    return {"id": oid, "target": target, "price": round(float(body.price), 2), "status": "open"}


@app.get("/bank/intel/offers")
def bank_intel_offers(banker: str = Depends(require_banker)):
    with Session(engine()) as s:
        rows = s.scalars(select(IntelOffer).order_by(IntelOffer.id.desc()).limit(30)).all()
    return {"offers": [{"id": o.id, "target": o.target, "price": float(o.price),
                        "status": o.status, "buyer": o.buyer} for o in rows]}


@app.get("/intel/offers")
def intel_offers():
    """Offres d'intel disponibles (vue attaquant, non authentifié = console attaquant)."""
    with Session(engine()) as s:
        rows = s.scalars(select(IntelOffer).where(IntelOffer.status == "open")
                         .order_by(IntelOffer.id.desc()).limit(30)).all()
    return {"offers": [{"id": o.id, "target": o.target, "price": float(o.price)} for o in rows]}


@app.post("/intel/offers/{offer_id}/buy")
def intel_buy(offer_id: int, x_player: str = Header(default=None)):
    """L'attaquant achète l'intel (payé avec le butin). Débloque la recon sur la
    cible côté /game (solde approx + présence de livret). Tracé (métrique IA)."""
    if _cooldown_remaining() > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {_cooldown_remaining()}s")
    buyer = ((x_player or "").strip()[:32]) or "attaquant"
    with Session(engine()) as s:
        o = s.scalar(select(IntelOffer).where(IntelOffer.id == offer_id).with_for_update())
        if o is None or o.status != "open":
            raise HTTPException(404, "offre indisponible")
        price = float(o.price)
        with game_lock:
            loot = game_state["loot"]
        if loot < price:
            raise HTTPException(402, f"butin insuffisant (prix {price:.0f} €, butin {loot:.0f} €)")
        tu = s.scalar(select(User).where(User.username == o.target))
        tacc = s.scalar(select(Account).where(Account.user_id == tu.id)) if tu else None
        if tacc is None:
            raise HTTPException(404, "cible de l'offre introuvable")
        bal = float(tacc.balance)
        sav = float(tacc.savings)
        o.status = "sold"
        o.buyer = buyer
        s.commit()
        target = o.target
    intel_line = (f"[INSIDER] {target} : solde {_bucket(bal)}, "
                  f"livret {'OUI ' + _bucket(sav) if sav > 0 else 'non'}.")
    with game_lock:
        game_state["loot"] = round(game_state["loot"] - price, 2)
        game_state["victim"] = target
        game_state["recon_count"] = max(game_state["recon_count"], GAME_RECON_FOR_HEIST)
        if target not in game_state["discovered"]:
            game_state["discovered"].append(target)
        if intel_line not in game_state["intel"]:
            game_state["intel"].append(intel_line)
        game_state["intel"] = game_state["intel"][-8:]
        game_state["insider_count"] = game_state.get("insider_count", 0) + 1
        loot_now = game_state["loot"]
    GAME_INSIDER.inc()
    GAME_LOOT.set(loot_now)
    _bump_suspicion(buyer, 0.10, reason="achat d'intel insider")
    print(f"[GAME] INSIDER buy offer={offer_id} buyer={buyer} target={target} price={price}", flush=True)
    return {"ok": True, "target": target, "price": price, "intel": intel_line,
            "ready_to_heist": True, **_game_public()}


@app.get("/admin/integrity")
def integrity(x_admin_token: str = Header(default=None)):
    """Contrôle d'intégrité des données (réponse à une compromission).

    Réponse différente de la restauration de disponibilité : on vérifie que la
    base n'a pas été altérée (comptes attendus, pas d'utilisateur suspect,
    soldes cohérents).
    """
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    suspicious_rx = re.compile(r"(?i)('|--|;|union|drop|select|<script|=)")
    with Session(engine()) as s:
        users = s.scalars(select(User)).all()
        accounts = s.scalars(select(Account)).all()
        total = sum(float(a.balance) for a in accounts)
        suspicious = [u.username for u in users if suspicious_rx.search(u.username)]
        negative = [a.id for a in accounts if float(a.balance) < 0]
    ok = not suspicious and not negative
    return {
        "integrity_ok": ok,
        "users_count": len(users),
        "accounts_count": len(accounts),
        "total_balance": round(total, 2),
        "suspicious_users": suspicious,
        "negative_balances": negative,
    }


# ---------------- JEU DE HACKER : reconnaissance, fuite, vol plafonné ----------------
def _cooldown_remaining() -> float:
    return max(0.0, round(game_state["blocked_until"] - time.time(), 1))


def _bucket(v: float) -> str:
    """Soldes 'approximatifs' (fuite progressive) : fourchette, pas la valeur exacte."""
    lo = int(v // 100) * 100
    return f"~{lo}–{lo + 100} €"


def _game_public() -> dict:
    with game_lock:
        g = dict(game_state)
    cd = _cooldown_remaining()
    g["blocked"] = cd > 0
    g["cooldown_remaining"] = cd
    g["loot_cap_remaining"] = round(max(0.0, GAME_LOOT_CAP - g["loot"] - g["loot_neutralized"]), 2)
    g["degraded"] = degraded["on"]
    d = _distraction()
    g["distraction"] = round(d, 2)
    g["distraction_min"] = DISTRACT_MIN
    g["ia_weakened"] = d >= DISTRACT_MIN
    return g


@app.get("/game/state")
def game_state_public():
    """État du jeu lu en direct par la console attaquant (toujours disponible)."""
    GAME_BLOCKED.set(1 if _cooldown_remaining() > 0 else 0)
    return _game_public()


@app.get("/game/suspicion")
def game_suspicion():
    """P4 — état de la détection par IP/acteur : score de suspicion, proba de
    blocage et cooldown restant PAR acteur (pour la console et le cockpit).
    Isolation : chaque acteur a son propre score, on ne bloque que le suspect."""
    now = time.time()
    with susp_lock:
        keys = list(suspicion.keys())
    actors = []
    for actor in keys:
        e = _susp(actor)  # applique la décroissance
        is_primary = actor == "attaquant"
        cd = _cooldown_remaining() if is_primary else max(0.0, round(e["blocked_until"] - now, 1))
        actors.append({"actor": actor, "ip": e.get("ip", ""), "score": round(e["score"], 3),
                       "p_block": round(_block_prob(e["score"]), 3),
                       "cooldown_remaining": cd, "blocked": cd > 0,
                       "reason": e.get("last_reason", "")})
    actors.sort(key=lambda a: a["score"], reverse=True)
    return {"s0": SUSP_S0, "cooldown": SUSP_COOLDOWN, "actors": actors}


class TargetIn(BaseModel):
    username: str


@app.post("/game/target")
def game_target(body: TargetIn):
    """Choix de la CIBLE courante (l'attaquant vise qui il veut). On vérifie que
    c'est bien un client de rôle 'client'. Changer de cible repart d'une recon
    vierge (les infos fuitées valaient pour l'ancienne cible) ; le butin est conservé."""
    name = (body.username or "").strip()
    is_rival = name in rivals
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == name))
    if not is_rival and (u is None or (u.role or "client") not in ("client", "bank")):
        raise HTTPException(400, "cible invalide — un client, la banque ou un attaquant")
    with game_lock:
        changed = name != game_state["victim"]
        game_state["victim"] = name
        if changed:
            game_state["recon_count"] = 0
            game_state["intel"] = []
    print(f"[GAME] TARGET -> {name}", flush=True)
    return {"ok": True, "victim": name, **_game_public()}


@app.post("/game/recon")
def game_recon(request: Request, x_player: str = Header(default=None)):
    """Sonde de reconnaissance : fuite progressive d'infos sur la cible (par
    conception, pour le jeu). Instrumentée (compteur Prometheus + log) pour que
    l'IA puisse repérer un motif d'énumération. Monte la suspicion de l'acteur."""
    actor, is_primary = _resolve_actor(request, x_player)
    cd = _actor_cooldown(actor, is_primary)
    if cd > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {cd}s")
    d = _distraction()
    if d < DISTRACT_MIN:
        raise HTTPException(409, "l'IA analyse tout le trafic — lance des attaques (vecteurs) "
                                 "pour la distraire AVANT de sonder")
    GAME_RECON.inc()
    # Suspicion atténuée quand l'IA est distraite par la charge d'attaque.
    _bump_suspicion(actor, 0.04 * (1 - 0.7 * d), _actor_ip(request), "reconnaissance")
    _maybe_block(actor, is_primary, "énumération repérée par l'IA")
    with Session(engine()) as s:
        clients = s.execute(
            select(User.username, Account.balance, Account.savings)
            .join(Account, Account.user_id == User.id)
            .where(User.role == "client").order_by(Account.balance.desc())
        ).all()
    victim = game_state["victim"]
    vrow = next((r for r in clients if r.username == victim), (clients[0] if clients else None))
    # Livrets supplémentaires de la cible (révélés à partir de l'étape 3 ; ciblables au vol).
    vlivrets = []
    if vrow is not None:
        with Session(engine()) as s:
            vu = s.scalar(select(User).where(User.username == vrow.username))
            if vu is not None:
                vlivrets = [{"id": lv.id, "name": lv.name, "bucket": _bucket(float(lv.balance))}
                            for lv in s.scalars(select(Livret).where(Livret.user_id == vu.id)).all()]
    with game_lock:
        game_state["recon_count"] += 1
        step = game_state["recon_count"]
        if step == 1:
            game_state["discovered"] = [r.username for r in clients]
            names = ", ".join(r.username for r in clients[:6]) or "aucun"
            item = f"Annuaire exposé : {len(clients)} comptes clients détectés ({names})."
        elif step == 2 and vrow is not None:
            item = f"Cible « {vrow.username} » : solde courant {_bucket(float(vrow.balance))} (approx.)."
        elif step == 3 and vrow is not None:
            game_state["victim_livrets"] = vlivrets
            has = float(vrow.savings) > 0
            base = (f"Cible « {vrow.username} » : LIVRET d'épargne ({_bucket(float(vrow.savings))})."
                    if has else f"Cible « {vrow.username} » : pas de livret d'épargne principal.")
            if vlivrets:
                base += " Livrets supplémentaires : " + ", ".join(f"{lv['name']} ({lv['bucket']})" for lv in vlivrets) + "."
            item = base
        else:
            game_state["victim_livrets"] = vlivrets
            item = "Infos suffisantes — un retrait ciblé et PLAFONNÉ est possible."
        if item not in game_state["intel"]:
            game_state["intel"].append(item)
        game_state["intel"] = game_state["intel"][-8:]
        count = game_state["recon_count"]
    print(f"[GAME] recon #{count} victim={victim} -> {item}", flush=True)
    return {"ok": True, "recon_count": count, "leaked": item,
            "ready_to_heist": count >= GAME_RECON_FOR_HEIST, **_game_public()}


# ---- P3.5 : facteurs des upgrades hacker + probabilités de se faire cramer ----
def _stealth_factor() -> float:
    return max(0.1, 1.0 - 0.10 * _hk_level("stealth"))   # furtivité : baisse la proba de catch


def _toolkit_factor() -> float:
    return 1.0 + 0.50 * _hk_level("toolkit")             # boîte à outils : plafond de vol plus haut


def _recon_needed() -> int:
    return max(1, GAME_RECON_FOR_HEIST - _hk_level("decoder"))  # décodeur : moins de recon requise


def _catch_client(amount: float) -> float:
    with game_lock:
        freq = int(game_state.get("client_heists", 0))
    p = (CATCH_CLIENT_BASE
         + CATCH_CLIENT_K_AMT * (amount / max(1.0, HEIST_CLIENT_MAX))
         + CATCH_CLIENT_K_FREQ * freq) * _stealth_factor()
    return min(0.95, max(0.02, p))


def _catch_bank(amount: float) -> float:
    p = (CATCH_BANK_BASE + CATCH_BANK_K * (amount / max(1.0, HEIST_BANK_MAX))) * _stealth_factor()
    return min(0.98, max(0.05, p))


class HeistIn(BaseModel):
    amount: float | None = None
    source: str | None = "courant"   # courant | epargne | livret (cibles clients)
    livret_id: int | None = None     # si source=livret : quel livret précis voler
    target: str | None = None        # cible explicite (sinon la cible courante)
    target_type: str | None = None   # auto-détecté : client | bank | attacker


@app.get("/game/targets")
def game_targets():
    """Toutes les cibles possibles : clients, la banque (coffre), autres attaquants (PvP)."""
    with Session(engine()) as s:
        clients = list(s.scalars(select(User.username).where(User.role == "client")
                                 .order_by(User.username)).all())
        bank = s.scalar(select(User.username).where(User.role == "bank"))
    with game_lock:
        rv = [{"handle": h, "loot": round(v, 2)} for h, v in rivals.items()]
        current = game_state.get("victim")
    return {"clients": clients, "bank": bank, "attackers": rv, "current": current}


def _heist_client(target: str, body: HeistIn):
    src = (body.source or "courant").lower()
    # Plafond relevé par la distraction de l'IA : plus elle est occupée, plus on vole gros.
    cap = HEIST_CLIENT_MAX * _toolkit_factor() * (1 + 2 * _distraction())
    want = float(body.amount) if (body.amount and body.amount > 0) else cap
    want = min(want, cap)
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == target))
        if u is None:
            raise HTTPException(404, "cible introuvable")
        lv = None
        if src == "livret" and body.livret_id:
            lv = s.scalar(select(Livret).where(Livret.id == body.livret_id,
                                               Livret.user_id == u.id).with_for_update())
            if lv is None:
                raise HTTPException(404, "livret ciblé introuvable")
            acc = s.scalar(select(Account).where(Account.user_id == u.id))  # pour l'id (transactions)
            avail = float(lv.balance)
            label = f" {lv.name}"
        else:
            acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
            if acc is None:
                raise HTTPException(404, "cible introuvable")
            avail = float(acc.savings if src == "epargne" else acc.balance)
            label = " LIVRET" if src == "epargne" else ""
        stolen = round(min(want, avail), 2)
        if stolen <= 0:
            raise HTTPException(402, "compte/livret vide — rien à exfiltrer")
        if lv is not None:
            lv.balance = float(lv.balance) - stolen
        elif src == "epargne":
            acc.savings = float(acc.savings) - stolen
        else:
            acc.balance = float(acc.balance) - stolen
        s.add(Transaction(account_id=acc.id, amount=stolen, type="debit",
                          recipient="⚠ EXFILTRATION" + label + " (jeu)", status="completed"))
        caught = random.random() <= _catch_client(stolen)
        if caught:  # claw-back immédiat : la victime est remboursée
            if lv is not None:
                lv.balance = float(lv.balance) + stolen
            elif src == "epargne":
                acc.savings = float(acc.savings) + stolen
            else:
                acc.balance = float(acc.balance) + stolen
            s.add(Transaction(account_id=acc.id, amount=stolen, type="credit",
                              recipient="✓ CLAW-BACK (vol déjoué)", status="completed"))
        s.commit()
    if caught:
        fine = round(CLIENT_FINE_RATE * stolen, 2)
        with game_lock:
            game_state["loot"] = round(max(0.0, game_state["loot"] - fine), 2)
            game_state["loot_neutralized"] = round(game_state["loot_neutralized"] + stolen, 2)
            game_state["client_heists"] = int(game_state.get("client_heists", 0)) + 1
            loot = game_state["loot"]
        GAME_THEFT.labels(target_type="client", result="caught").inc()
        GAME_LOOT.set(loot)
        print(f"[GAME] HEIST CLIENT CAUGHT target={target} stolen={stolen} fine={fine} loot={loot}", flush=True)
        ws_manager.publish({"type": "tx", "from": target, "to": "✓ DÉFENSE", "amount": stolen, "op": "clawback"})
        return {"ok": False, "caught": True, "target": target, "target_type": "client",
                "attempted": stolen, "fine": fine, "loot": loot,
                "message": f"Cramé ! Vol déjoué, {target} remboursé, amende {fine:.0f} € sur ton butin.",
                **_game_public()}
    with game_lock:
        game_state["loot"] = round(game_state["loot"] + stolen, 2)
        game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + stolen, 2)
        game_state["heist_count"] += 1
        game_state["client_heists"] = int(game_state.get("client_heists", 0)) + 1
        loot = game_state["loot"]
    GAME_HEIST.inc()
    GAME_HEIST_AMT.inc(stolen)
    GAME_THEFT.labels(target_type="client", result="success").inc()
    GAME_LOOT.set(loot)
    print(f"[GAME] HEIST CLIENT target={target} src={src} stolen={stolen} loot={loot}", flush=True)
    ws_manager.publish({"type": "tx", "from": target, "to": "⚠ INCONNU", "amount": stolen, "op": "heist"})
    _check_win()
    return {"ok": True, "caught": False, "target": target, "target_type": "client",
            "stolen": stolen, "source": src, "loot": loot, **_game_public()}


def _heist_bank(target: str, body: HeistIn):
    cap = HEIST_BANK_MAX * _toolkit_factor() * (1 + 2 * _distraction())
    want = float(body.amount) if (body.amount and body.amount > 0) else cap
    want = min(want, cap)
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == target))
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
        if acc is None:
            raise HTTPException(404, "coffre introuvable")
        stolen = round(min(want, float(acc.balance)), 2)
        if stolen <= 0:
            raise HTTPException(402, "coffre vide — rien à exfiltrer")
        acc.balance = float(acc.balance) - stolen
        s.add(Transaction(account_id=acc.id, amount=stolen, type="debit",
                          recipient="⚠ BRAQUAGE BANQUE (jeu)", status="completed"))
        caught = random.random() <= _catch_bank(stolen)
        if caught:  # alarme du coffre : la banque est remboursée
            acc.balance = float(acc.balance) + stolen
            s.add(Transaction(account_id=acc.id, amount=stolen, type="credit",
                              recipient="✓ ALARME COFFRE (braquage déjoué)", status="completed"))
        s.commit()
    if caught:
        with game_lock:
            lost = game_state["loot"]
            game_state["loot_neutralized"] = round(game_state["loot_neutralized"] + lost, 2)
            game_state["loot"] = 0.0
            game_state["blocked_until"] = time.time() + BANK_BURN_COOLDOWN
            game_state["block_reason"] = "braquage de la banque repéré — perte totale du butin"
        GAME_THEFT.labels(target_type="bank", result="caught").inc()
        GAME_LOOT.set(0)
        GAME_BLOCKED.set(1)
        print(f"[GAME] HEIST BANK CAUGHT target={target} attempted={stolen} lost_all={lost}", flush=True)
        ws_manager.publish({"type": "tx", "from": target, "to": "✓ DÉFENSE", "amount": stolen, "op": "bankfail"})
        return {"ok": False, "caught": True, "target": target, "target_type": "bank",
                "attempted": stolen, "loot": 0.0, "lost_all": round(lost, 2),
                "message": f"CRAMÉ sur la banque ! Butin perdu en TOTALITÉ ({lost:.0f} €) "
                           f"+ cooldown {int(BANK_BURN_COOLDOWN)}s.", **_game_public()}
    with game_lock:
        game_state["loot"] = round(game_state["loot"] + stolen, 2)
        game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + stolen, 2)
        game_state["heist_count"] += 1
        loot = game_state["loot"]
    GAME_HEIST.inc()
    GAME_HEIST_AMT.inc(stolen)
    GAME_THEFT.labels(target_type="bank", result="success").inc()
    GAME_LOOT.set(loot)
    print(f"[GAME] HEIST BANK target={target} stolen={stolen} loot={loot}", flush=True)
    ws_manager.publish({"type": "tx", "from": "BANQUE", "to": "⚠ INCONNU", "amount": stolen, "op": "heist"})
    _check_win()
    return {"ok": True, "caught": False, "target": target, "target_type": "bank",
            "stolen": stolen, "loot": loot, **_game_public()}


def _heist_pvp(target: str):
    with game_lock:
        rival = float(rivals.get(target, 0.0))
    if rival <= 0:
        raise HTTPException(402, f"« {target} » n'a pas de butin à voler")
    stolen = round(min(rival, HEIST_PVP_MAX * _toolkit_factor()), 2)
    caught = random.random() <= (CATCH_PVP_BASE * _stealth_factor())
    if caught:
        with game_lock:
            fine = round(0.5 * stolen, 2)
            game_state["loot"] = round(max(0.0, game_state["loot"] - fine), 2)
            loot = game_state["loot"]
        GAME_THEFT.labels(target_type="attacker", result="caught").inc()
        GAME_LOOT.set(loot)
        return {"ok": False, "caught": True, "target": target, "target_type": "attacker",
                "attempted": stolen, "loot": loot,
                "message": f"Contre-hack de « {target} » ! Tu perds {fine:.0f} €.", **_game_public()}
    with game_lock:
        rivals[target] = round(max(0.0, rivals.get(target, 0.0) - stolen), 2)
        game_state["loot"] = round(game_state["loot"] + stolen, 2)
        game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + stolen, 2)
        game_state["heist_count"] += 1
        loot = game_state["loot"]
    GAME_HEIST.inc()
    GAME_HEIST_AMT.inc(stolen)
    GAME_THEFT.labels(target_type="attacker", result="success").inc()
    GAME_LOOT.set(loot)
    print(f"[GAME] HEIST PVP from={target} stolen={stolen} loot={loot}", flush=True)
    _check_win()
    return {"ok": True, "caught": False, "target": target, "target_type": "attacker",
            "stolen": stolen, "loot": loot, **_game_public()}


@app.post("/game/heist")
def game_heist(body: HeistIn, request: Request, x_player: str = Header(default=None)):
    """Vol généralisé (P3/P3.5) : cible CLIENT, BANQUE (coffre) ou ATTAQUANT (PvP).
    Retrait atomique (FOR UPDATE, jamais négatif) + risque de se faire cramer :
    - banque : très rentable, très risqué ; cramé = perte TOTALE du butin + cooldown 5 min ;
    - client : plus facile, difficulté exp. (fréquence+montant) ; cramé = perte 80 % + claw-back ;
    - attaquant : PvP, vole le butin d'un rival.
    Tout est tracé (game_theft_total{target_type,result}). La suspicion (P4) monte
    puis déclenche un blocage PROBABILISTE et ISOLÉ de l'acteur."""
    actor, is_primary = _resolve_actor(request, x_player)
    cd = _actor_cooldown(actor, is_primary)
    if cd > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {cd}s")
    distraction = _distraction()
    if distraction < DISTRACT_MIN:
        raise HTTPException(409, "l'IA surveille activement — distrais-la avec des attaques "
                                 "(vecteurs) avant de tenter un retrait")
    target = (body.target or game_state.get("victim") or "").strip()
    if not target:
        raise HTTPException(400, "aucune cible sélectionnée")
    # PvP : cible = un autre attaquant
    if (body.target_type or "").lower() == "attacker" or target in rivals:
        res = _heist_pvp(target)
        tt = "attacker"
    else:
        with Session(engine()) as s:
            tu = s.scalar(select(User).where(User.username == target))
            if tu is None:
                raise HTTPException(404, "cible introuvable")
            role = tu.role or "client"
        # recon requise (atténuée par le décodeur) pour clients et banque
        need = _recon_needed()
        with game_lock:
            rc = game_state["recon_count"]
        if rc < need:
            raise HTTPException(400, f"reconnaissance insuffisante ({rc}/{need})")
        if role == "bank" or target == BANK_USER:
            res, tt = _heist_bank(target, body), "bank"
        elif role == "client":
            res, tt = _heist_client(target, body), "client"
        else:
            raise HTTPException(400, "cible non volable")
    # P4 : la suspicion monte (plus fort si cramé) puis tirage de blocage isolé.
    caught = bool(res.get("caught"))
    delta = {"bank": 0.25, "client": 0.12, "attacker": 0.08}.get(tt, 0.12)
    if caught and tt != "bank":  # la banque cramée bloque déjà par elle-même
        delta += 0.3
    delta *= (1 - 0.6 * distraction)  # l'IA distraite détecte moins le vol
    _bump_suspicion(actor, delta, _actor_ip(request), f"vol {tt}" + (" (cramé)" if caught else ""))
    blocked, p = _maybe_block(actor, is_primary, "activité de vol suspecte")
    res["suspicion"] = round(_susp(actor)["score"], 3)
    res["p_block"] = p
    if blocked:
        res["blocked_now"] = True
    res.update(_game_public())
    return res


# ---- P3.5 : SHOP HACKER (payé avec le butin) ----
@app.get("/game/shop")
def game_shop():
    with game_lock:
        hk = dict(game_state.get("hk", {}))
        loot = game_state["loot"]
    items = [{"ukey": k, "label": c["label"], "desc": c["desc"], "level": int(hk.get(k, 0)),
              "next_cost": upg_cost(c["base"], c["growth"], int(hk.get(k, 0)))}
             for k, c in HSHOP.items()]
    return {"loot": loot, "items": items}


@app.post("/game/shop/buy")
def game_shop_buy(body: BuyIn):
    """Achat d'une upgrade hacker (payée avec le butin), coût exponentiel."""
    cfg = HSHOP.get(body.ukey)
    if cfg is None:
        raise HTTPException(404, "upgrade inconnue")
    with game_lock:
        lvl = int(game_state.get("hk", {}).get(body.ukey, 0))
        cost = upg_cost(cfg["base"], cfg["growth"], lvl)
        if game_state["loot"] < cost:
            raise HTTPException(402, f"butin insuffisant (coût {cost:.0f} €)")
        game_state["loot"] = round(game_state["loot"] - cost, 2)
        game_state.setdefault("hk", {})[body.ukey] = lvl + 1
        loot = game_state["loot"]
    GAME_LOOT.set(loot)
    print(f"[GAME] HACKER-SHOP buy {body.ukey} -> lvl {lvl + 1} (paid {cost}) loot={loot}", flush=True)
    return {"ok": True, "ukey": body.ukey, "level": lvl + 1, "paid": cost,
            "next_cost": upg_cost(cfg["base"], cfg["growth"], lvl + 1), "loot": loot}


# ---------------- P5 : phishing — campagnes + fausse page d'enchère ----------------
# Un attaquant crée une CAMPAGNE : un faux mail est envoyé aux clients ciblés avec
# un lien vers une FAUSSE page d'enchère servie par le backend (/phish/{id}, marquée
# en interne comme piège). Si une victime saisit sa mise, l'attaquant la VOLE à la
# clôture (plafonné, tracé), sauf si l'anti-fraude détecte la campagne (proba qui
# monte avec la suspicion -> métrique + blocage).
class PhishIn(BaseModel):
    title: str | None = None
    item_value: float | None = None
    min_bid: float | None = 0
    lure: str | None = None
    targets: list[str] | None = None   # clients ciblés (vide/None = tous les clients)


def _phish_page_html(a) -> str:
    """Fausse page d'enchère (auto-portée, aucun asset externe) servie à la victime."""
    title = html.escape(a.title or "Enchère privée")
    val = float(a.item_value)
    minb = float(a.min_bid)
    closed = a.status == "closed"
    banner = ("<p class='closed'>Cette vente est terminée.</p>" if closed else
              f"""<form id='f' onsubmit='return send(event)'>
      <label>Votre identifiant client<input name='u' required></label>
      <label>Votre mise (EUR)<input name='a' type='number' min='{minb or 1}' step='1' required></label>
      <button type='submit'>Enchérir maintenant</button></form>
    <p id='msg'></p>
    <script>
    async function send(e){{e.preventDefault();
      const u=document.querySelector('[name=u]').value, a=parseFloat(document.querySelector('[name=a]').value);
      const r=await fetch(location.pathname+'/bid',{{method:'POST',headers:{{'Content-Type':'application/json'}},
        body:JSON.stringify({{username:u,amount:a}})}});
      const j=await r.json(); document.getElementById('msg').textContent = j.message || JSON.stringify(j);
      if(r.ok) document.getElementById('f').style.display='none';
      return false;}}
    </script>""")
    return f"""<!doctype html><html lang=fr><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>{title} — Enchère exclusive</title>
<style>
 body{{font-family:Montserrat,system-ui,sans-serif;background:#E4E6F3;color:#261E48;margin:0;padding:24px}}
 .card{{max-width:460px;margin:24px auto;background:#fff;border-radius:14px;padding:28px;
   box-shadow:0 10px 30px rgba(38,30,72,.15)}}
 h1{{margin:0 0 4px;font-size:1.3rem}} .v{{font-size:2rem;font-weight:800;color:#261E48}}
 label{{display:block;margin:14px 0 4px;font-size:.9rem}} input{{width:100%;padding:10px;border:1px solid #A1A6D4;
   border-radius:8px;box-sizing:border-box}} button{{margin-top:16px;width:100%;padding:12px;border:0;
   border-radius:8px;background:#261E48;color:#fff;font-weight:700;cursor:pointer}}
 .badge{{display:inline-block;background:#A1A6D4;color:#261E48;border-radius:999px;padding:2px 10px;font-size:.75rem}}
 .closed{{color:#a33;font-weight:700}} small{{color:#6a6f99}}
</style></head><body><div class=card>
 <span class=badge>Enchère privée VIP</span>
 <h1>{title}</h1>
 <p>Valeur estimée <span class=v>{val:.0f} €</span> · mise min. {minb:.0f} €</p>
 {banner}
 <p><small>Offre réservée — accès personnel. (Démo pédagogique : page piège de phishing.)</small></p>
</div></body></html>"""


@app.post("/game/phishing")
def game_phishing(body: PhishIn, request: Request, x_player: str = Header(default=None)):
    """Crée une CAMPAGNE de phishing : fausse enchère (piège) + faux mail d'invitation
    envoyé aux clients ciblés, avec le lien vers la fausse page /phish/{id}."""
    actor, is_primary = _resolve_actor(request, x_player)
    cd = _actor_cooldown(actor, is_primary)
    if cd > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {cd}s")
    title = (body.title or "Offre VIP exceptionnelle").strip()[:140]
    val = round(float(body.item_value or 1000), 2)
    minb = round(max(0.0, float(body.min_bid or 0)), 2)
    lure = (body.lure or "").strip()[:400]
    wanted = [t.strip() for t in (body.targets or []) if t and t.strip()]
    with Session(engine()) as s:
        a = Auction(title=title, item_value=val, min_bid=minb,
                    status="open", created_by=actor, phish=1, beneficiary=actor)
        s.add(a)
        s.flush()
        aid = a.id
        if wanted:
            clients = s.scalars(select(User).where(User.username.in_(wanted),
                                                   User.role == "client")).all()
        else:
            clients = s.scalars(select(User).where(User.role == "client")).all()
        link = f"/phish/{aid}"
        base = lure or (f"Felicitations ! Vous etes selectionne pour l'enchere privee "
                        f"« {title} » (valeur estimee {val:.0f} EUR).")
        for cu in clients:
            s.add(Mail(user_id=cu.id, subject=f"Invitation VIP : {title}",
                       body=f"{base}\nAcceder a votre enchere personnelle : {link}", kind="auction"))
        targeted = [cu.username for cu in clients]
        s.commit()
    GAME_PHISH.labels(result="sent").inc()
    _bump_suspicion(actor, 0.08, _actor_ip(request), "campagne de phishing envoyée")
    ws_manager.publish({"type": "mail"})
    print(f"[GAME] PHISH campaign by={actor} id={aid} targets={len(targeted)}", flush=True)
    return {"ok": True, "campaign_id": aid, "page": link, "targeted": targeted,
            "count": len(targeted), **_game_public()}


@app.get("/game/phishing")
def game_phishing_list(request: Request, x_player: str = Header(default=None)):
    """Campagnes de l'attaquant + nombre de victimes ayant mordu + butin volé."""
    actor, _ = _resolve_actor(request, x_player)
    with Session(engine()) as s:
        rows = s.scalars(select(Auction).where(Auction.phish == 1, Auction.beneficiary == actor)
                         .order_by(Auction.id.desc()).limit(20)).all()
        out = []
        for a in rows:
            biters = s.scalars(select(func.count(func.distinct(Bid.username)))
                               .where(Bid.auction_id == a.id)).first()
            out.append({"id": a.id, "title": a.title, "status": a.status, "page": f"/phish/{a.id}",
                        "biters": int(biters or 0),
                        "stolen": float(a.winning_bid) if (a.status == "closed" and a.winning_bid) else None})
    return {"campaigns": out}


@app.get("/phish/{auction_id}", response_class=HTMLResponse)
def phish_page(auction_id: int):
    """Fausse page d'enchère servie par le backend (le piège sur lequel la victime
    atterrit depuis le faux mail). Marquée en interne comme phishing."""
    with Session(engine()) as s:
        a = s.scalar(select(Auction).where(Auction.id == auction_id, Auction.phish == 1))
        if a is None:
            return HTMLResponse("<h1>Enchère introuvable</h1>", status_code=404)
        page = _phish_page_html(a)
    return HTMLResponse(page)


class PhishBidIn(BaseModel):
    username: str
    amount: float


@app.post("/phish/{auction_id}/bid")
def phish_bid(auction_id: int, body: PhishBidIn):
    """Saisie de la victime sur la fausse page : on enregistre sa mise (débit différé
    à la clôture). Non authentifié par conception (page piège externe)."""
    uname = (body.username or "").strip()
    amount = round(float(body.amount or 0), 2)
    with Session(engine()) as s:
        a = s.scalar(select(Auction).where(Auction.id == auction_id, Auction.phish == 1))
        if a is None:
            raise HTTPException(404, "enchère introuvable")
        if a.status == "closed":
            raise HTTPException(400, "cette vente est terminée")
        u = s.scalar(select(User).where(User.username == uname))
        if u is None or (u.role or "client") != "client":
            raise HTTPException(400, "identifiant inconnu")
        if amount <= 0 or amount < float(a.min_bid):
            raise HTTPException(400, f"mise minimale {float(a.min_bid):.0f} EUR")
        s.add(Bid(auction_id=a.id, username=uname, amount=amount))
        s.commit()
    GAME_PHISH.labels(result="bite").inc()
    print(f"[GAME] PHISH bite auction={auction_id} victim={uname} amount={amount}", flush=True)
    return {"ok": True, "message": "Mise enregistree ! Vous serez recontacte a la cloture de l'enchere."}


@app.post("/game/phishing/{auction_id}/close")
def game_phishing_close(auction_id: int, request: Request, x_player: str = Header(default=None)):
    """Clôture de campagne : la mise de CHAQUE victime solvable est VOLÉE (plafonné
    par le cap du butin), SAUF si l'anti-fraude détecte l'arnaque (proba qui monte
    avec la suspicion de l'attaquant) -> rien volé, victimes alertées, blocage probable."""
    actor, is_primary = _resolve_actor(request, x_player)
    cd = _actor_cooldown(actor, is_primary)
    if cd > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {cd}s")
    with game_lock:
        cap_left = GAME_LOOT_CAP - game_state["loot"] - game_state["loot_neutralized"]
    victims = []
    all_biters = []
    detected = False
    with Session(engine()) as s:
        a = s.scalar(select(Auction).where(Auction.id == auction_id, Auction.phish == 1).with_for_update())
        if a is None:
            raise HTTPException(404, "campagne introuvable")
        if a.beneficiary != actor:
            raise HTTPException(403, "ce n'est pas ta campagne")
        if a.status == "closed":
            raise HTTPException(400, "campagne déjà close")
        rows = s.execute(select(Bid.username, func.max(Bid.amount)).where(Bid.auction_id == a.id)
                         .group_by(Bid.username)).all()
        all_biters = [r[0] for r in rows]
        if not rows:
            a.status = "closed"
            s.commit()
            GAME_PHISH.labels(result="empty").inc()
            return {"ok": True, "result": "empty", "message": "personne n'a mordu à l'hameçon",
                    **_game_public()}
        score = _susp(actor)["score"]
        detected = random.random() <= min(0.95, PHISH_DETECT_BASE + 0.5 * score)
        title = a.title
        if detected:
            for uname in all_biters:
                vu = s.scalar(select(User).where(User.username == uname))
                if vu is not None:
                    s.add(Mail(user_id=vu.id, subject="Alerte fraude : fausse enchere bloquee",
                               body=f"Notre systeme anti-fraude a bloque une FAUSSE enchere « {title} » "
                                    f"qui vous visait. Aucun debit. Mefiez-vous des offres trop belles.",
                               kind="info"))
            a.status = "closed"
            a.winner = None
            a.winning_bid = None
            s.commit()
        else:
            for uname, amt in rows:
                vu = s.scalar(select(User).where(User.username == uname))
                if vu is None or (vu.role or "client") != "client":
                    continue
                acc = s.scalar(select(Account).where(Account.user_id == vu.id).with_for_update())
                if acc is None:
                    continue
                stolen = round(min(float(amt), float(acc.balance), max(0.0, cap_left)), 2)
                if stolen <= 0:
                    continue
                acc.balance = float(acc.balance) - stolen
                s.add(Transaction(account_id=acc.id, amount=stolen, type="debit",
                                  recipient=f"⚠ PHISHING « {title} » (jeu)", status="completed"))
                s.add(Mail(user_id=vu.id, subject=f"Enchere « {title} » : debit de votre mise",
                           body=f"Votre mise de {stolen:.0f} EUR a ete prelevee pour « {title} ». "
                                f"(En realite : fausse enchere — vous avez ete victime d'un phishing.)",
                           kind="info"))
                victims.append({"username": uname, "stolen": stolen})
                cap_left -= stolen
            a.status = "closed"
            a.winner = victims[0]["username"] if victims else None
            a.winning_bid = round(sum(v["stolen"] for v in victims), 2) if victims else None
            s.commit()
    if detected:
        GAME_PHISH.labels(result="detected").inc()
        _bump_suspicion(actor, 0.45, _actor_ip(request), "campagne de phishing détectée")
        blocked, _p = _maybe_block(actor, is_primary, "phishing détecté par l'anti-fraude")
        ws_manager.publish({"type": "mail"})
        print(f"[GAME] PHISH DETECTED by={actor} campaign={auction_id} biters={len(all_biters)}", flush=True)
        return {"ok": False, "result": "detected", "victims": all_biters,
                "message": "Fraude détectée par l'anti-fraude — aucune mise volée, victimes alertées.",
                "blocked_now": blocked, **_game_public()}
    total = round(sum(v["stolen"] for v in victims), 2)
    if total <= 0:
        GAME_PHISH.labels(result="empty").inc()
        return {"ok": True, "result": "empty", "message": "aucune victime solvable", **_game_public()}
    with game_lock:
        game_state["loot"] = round(game_state["loot"] + total, 2)
        game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + total, 2)
        loot = game_state["loot"]
    GAME_LOOT.set(loot)
    GAME_PHISH.labels(result="success").inc()
    _bump_suspicion(actor, 0.15, _actor_ip(request), "phishing réussi")
    blocked, _p = _maybe_block(actor, is_primary, "phishing répété suspect")
    ws_manager.publish({"type": "mail"})
    ws_manager.publish({"type": "tx", "from": victims[0]["username"], "to": "⚠ INCONNU",
                        "amount": total, "op": "phish"})
    _check_win()
    print(f"[GAME] PHISH SUCCESS by={actor} campaign={auction_id} victims={len(victims)} total={total} loot={loot}", flush=True)
    return {"ok": True, "result": "success", "victims": victims, "stolen_total": total,
            "loot": loot, "blocked_now": blocked, **_game_public()}


@app.post("/game/admin/block")
def game_block(body: dict = Body(...), x_admin_token: str = Header(default=None)):
    """L'orchestrateur bloque l'attaquant pour `seconds` (cooldown visible côté console)."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    seconds = float(body.get("seconds", 120))
    with game_lock:
        game_state["blocked_until"] = time.time() + seconds
        game_state["block_reason"] = str(body.get("reason", "activité anormale détectée par l'IA"))
    GAME_BLOCKED.set(1)
    print(f"[GAME] BLOCK {seconds}s — {game_state['block_reason']}", flush=True)
    return _game_public()


@app.post("/game/admin/clawback")
def game_clawback(x_admin_token: str = Header(default=None)):
    """Réponse de la défense : restaure le butin à la cible (intégrité / secours sain)
    -> l'argent volé ne 'gagne' pas si l'IA bascule à temps."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    with game_lock:
        outstanding = game_state["loot"]
    if outstanding > 0:
        with Session(engine()) as s:
            u = s.scalar(select(User).where(User.username == game_state["victim"]))
            acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
            if acc is not None:
                acc.balance = float(acc.balance) + outstanding
                s.add(Transaction(account_id=acc.id, amount=outstanding, type="credit",
                                  recipient="✓ RESTAURATION (défense IA)", status="completed"))
                s.commit()
    with game_lock:
        game_state["loot_neutralized"] = round(game_state["loot_neutralized"] + outstanding, 2)
        game_state["loot"] = 0.0
    GAME_LOOT.set(0)
    print(f"[GAME] CLAWBACK restored={outstanding} to {game_state['victim']}", flush=True)
    return {"restored": outstanding, **_game_public()}


@app.post("/game/admin/reset")
def game_reset(x_admin_token: str = Header(default=None)):
    """Réinitialise la partie (rejouer la démo)."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    with game_lock:
        game_state.update({"victim": GAME_VICTIM, "loot": 0.0, "loot_neutralized": 0.0,
                           "exfiltrated_total": 0.0, "recon_count": 0, "heist_count": 0,
                           "intel": [], "discovered": [], "blocked_until": 0.0, "block_reason": "",
                           "insider_count": 0, "dino_hijack": None, "hk": {}, "client_heists": 0})
        rivals.clear()
    GAME_LOOT.set(0)
    GAME_BLOCKED.set(0)
    return _game_public()


# ---------------- P2.7 : mini-jeu Dino (récolte) + hack détournement ----------------
class DinoClaim(BaseModel):
    score: float
    multiplier: int | None = 1


@app.post("/dino/claim")
def dino_claim(body: DinoClaim, user: str = Depends(current_user)):
    """Récolte Dino : convertit un score (plafonné) en argent crédité au joueur.
    Validé serveur : plafond par claim + cooldown anti-rafale + multiplicateur borné.
    Si un détournement est armé sur ce joueur, une part est exfiltrée vers l'attaquant."""
    now = time.time()
    with game_lock:
        remaining = DINO_COOLDOWN - (now - dino_last.get(user, 0.0))
        if remaining > 0:
            raise HTTPException(429, f"patiente {round(remaining, 1)}s avant une nouvelle récolte")
        dino_last[user] = now
        hijack = game_state.get("dino_hijack")
    mult = _dino_mult(body.multiplier)
    raw = max(0.0, min(float(body.score or 0), DINO_MAX_SCORE))
    earned = round(min(raw * mult * DINO_COIN_VALUE, DINO_CLAIM_CAP), 2)
    if earned <= 0:
        raise HTTPException(400, "score nul")
    hijacked = hijack is not None and hijack.get("target") == user
    diverted = 0.0
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        if (u.role or "client") != "client":
            raise HTTPException(403, "réservé aux clients")
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update())
        if hijacked:
            with game_lock:
                cap_left = GAME_LOOT_CAP - game_state["loot"] - game_state["loot_neutralized"]
            diverted = round(min(earned * DINO_HIJACK_SHARE, GAME_HEIST_MAX, max(0.0, cap_left)), 2)
        credit = round(earned - diverted, 2)
        acc.balance = float(acc.balance) + credit
        s.add(Transaction(account_id=acc.id, amount=credit, type="credit",
                          recipient=f"DINO (x{mult})", status="completed"))
        if diverted > 0:
            s.add(Transaction(account_id=acc.id, amount=diverted, type="debit",
                              recipient="⚠ GAIN DÉTOURNÉ (jeu)", status="completed"))
        s.commit()
        new_balance = float(acc.balance)
    if hijacked:
        with game_lock:
            game_state["dino_hijack"] = None
            if diverted > 0:
                game_state["loot"] = round(game_state["loot"] + diverted, 2)
                game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + diverted, 2)
            loot_now = game_state["loot"]
        if diverted > 0:
            GAME_LOOT.set(loot_now)
            GAME_DINO_HIJACK.labels(result="hit").inc()
            print(f"[GAME] DINO-HIJACK HIT target={user} diverted={diverted} loot={loot_now}", flush=True)
            ws_manager.publish({"type": "tx", "from": user, "to": "⚠ INCONNU",
                                "amount": diverted, "op": "hijack"})
    ws_manager.publish({"type": "tx", "from": "DINO", "to": user, "amount": credit, "op": "dino"})
    _check_win()
    return {"ok": True, "earned": earned, "credited": credit, "diverted": diverted,
            "multiplier": mult, "balance": new_balance, "hijacked": hijacked and diverted > 0}


class HijackIn(BaseModel):
    target: str


@app.post("/game/dino-hijack")
def dino_hijack(body: HijackIn, request: Request, x_player: str = Header(default=None)):
    """Hack attaquant : tente de détourner le prochain gain Dino d'un client.
    Protégé par l'IA : proba de succès qui chute avec l'activité déjà menée ;
    sur échec, risque de blocage (cooldown). Succès => détournement armé.
    Monte la suspicion de l'acteur (P4)."""
    actor, is_primary = _resolve_actor(request, x_player)
    cd = _actor_cooldown(actor, is_primary)
    if cd > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {cd}s")
    target = (body.target or "").strip()
    with Session(engine()) as s:
        tu = s.scalar(select(User).where(User.username == target))
        if tu is None or (tu.role or "client") != "client":
            raise HTTPException(400, "cible invalide — un client existant est requis")
    with game_lock:
        heat = int(game_state.get("heist_count", 0)) + int(game_state.get("insider_count", 0))
    p_success = max(0.1, DINO_HIJACK_P - 0.05 * heat)  # plus tu abuses, plus c'est dur
    if random.random() <= p_success:
        with game_lock:
            game_state["dino_hijack"] = {"target": target}
        GAME_DINO_HIJACK.labels(result="armed").inc()
        _bump_suspicion(actor, 0.12, _actor_ip(request), "détournement Dino armé")
        print(f"[GAME] DINO-HIJACK ARMED target={target} p={p_success:.2f}", flush=True)
        return {"ok": True, "armed": True, "target": target,
                "message": f"Détournement armé sur « {target} » : son prochain gain Dino "
                           f"sera en partie exfiltré.", **_game_public()}
    GAME_DINO_HIJACK.labels(result="fail").inc()
    _bump_suspicion(actor, 0.30, _actor_ip(request), "détournement Dino raté")
    blocked_susp, _p = _maybe_block(actor, is_primary, "détournement Dino repéré par l'IA")
    if blocked_susp or random.random() <= DINO_HIJACK_BLOCK_P:
        if not blocked_susp:
            with game_lock:
                game_state["blocked_until"] = time.time() + DINO_HIJACK_COOLDOWN
                game_state["block_reason"] = "détournement Dino repéré par l'IA"
            GAME_BLOCKED.set(1)
        print(f"[GAME] DINO-HIJACK FAIL+BLOCK target={target}", flush=True)
        return {"ok": False, "armed": False, "blocked": True,
                "message": "Détournement repéré par l'IA — tu es bloqué (cooldown).",
                **_game_public()}
    print(f"[GAME] DINO-HIJACK FAIL target={target} p={p_success:.2f}", flush=True)
    return {"ok": False, "armed": False, "blocked": False,
            "message": "Échec du détournement — réessaie.", **_game_public()}


@app.post("/admin/degrade")
def admin_degrade(body: dict = Body(...), x_admin_token: str = Header(default=None)):
    """Bascule : met (ou retire) le noeud en mode dégradé (503 métier). N'a d'effet
    que si GAME_DEGRADE=1 (montage 2 PC avec un vrai secours)."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    want = bool(body.get("enabled", False))
    degraded["on"] = want and GAME_DEGRADE
    return {"degraded": degraded["on"], "gated_off": want and not GAME_DEGRADE}


# ---------------- Réplication / haute disponibilité ----------------
@app.get("/repl/status")
def repl_status():
    return repl_state


def _local_dump():
    """Snapshot de l'état local (utilisateurs, soldes, transactions idempotentes)."""
    with Session(engine()) as s:
        users = s.scalars(select(User)).all()
        accounts = s.scalars(select(Account)).all()
        id2name = {u.id: u.username for u in users}
        acc_by_user = {}
        out_accounts = []
        for a in accounts:
            uname = id2name.get(a.user_id)
            acc_by_user[a.id] = uname
            out_accounts.append({"username": uname, "balance": float(a.balance),
                                 "savings": float(a.savings), "currency": a.currency})
        txs = s.scalars(select(Transaction).where(Transaction.idem_key.is_not(None))).all()
        out_tx = [{"idem_key": t.idem_key, "username": acc_by_user.get(t.account_id),
                   "amount": float(t.amount), "type": t.type, "recipient": t.recipient,
                   "status": t.status} for t in txs]
    return {
        "users": [{"username": u.username, "password_hash": u.password_hash} for u in users],
        "accounts": out_accounts,
        "transactions": out_tx,
    }


@app.get("/repl/dump")
def repl_dump(x_repl_token: str = Header(default=None)):
    """État à répliquer (lu par le secours). Protégé par un token interne."""
    if x_repl_token != REPL_TOKEN:
        raise HTTPException(403, "forbidden")
    return _local_dump()


@app.post("/repl/restore")
def repl_restore(data: dict = Body(...), x_repl_token: str = Header(default=None)):
    """Réconciliation : le secours pousse son état au principal qui revient (failback)."""
    if x_repl_token != REPL_TOKEN:
        raise HTTPException(403, "forbidden")
    apply_dump(data)
    ha_event("État reçu du secours et appliqué — réconciliation après panne", "action")
    return {"restored": True}


def _peer_status():
    """État du pair (principal<->secours), ou injoignable."""
    if not PEER_API_URL:
        return {"reachable": False}
    try:
        r = requests.get(f"{PEER_API_URL}/repl/status", timeout=2)
        if r.status_code == 200:
            d = r.json()
            d["reachable"] = True
            return d
    except Exception:  # noqa: BLE001
        pass
    return {"reachable": False}


@app.get("/ha/cluster")
def ha_cluster():
    """Vue du cluster HA : les deux noeuds + qui fait autorité (pour le cockpit).

    Répond quel que soit le noeud joint (le principal normalement ; le secours si
    nginx a basculé). On reconstruit toujours les deux cartes PRINCIPAL/SECOURS.
    """
    me = dict(repl_state)
    me["reachable"] = True
    peer = _peer_status()
    peer_role_cfg = "backup" if ROLE == "primary" else "primary"
    nodes = {
        ROLE: {"name": me["name"], "role_cfg": ROLE, "promoted": me.get("promoted"),
               "reachable": True, "last_sync": me.get("last_sync"), "fails": me.get("fails", 0),
               "events": me.get("events", [])},
        peer_role_cfg: {"name": peer.get("name") or ("SECOURS" if ROLE == "primary" else "PRINCIPAL"),
                        "role_cfg": peer_role_cfg, "promoted": peer.get("promoted"),
                        "reachable": peer.get("reachable", False),
                        "last_sync": peer.get("last_sync"), "fails": peer.get("fails", 0),
                        "events": peer.get("events", [])},
    }
    principal = nodes["primary"]
    secours = nodes["backup"]
    if principal["reachable"] and principal.get("promoted"):
        serving = principal["name"]
    elif secours["reachable"] and secours.get("promoted"):
        serving = secours["name"]
    elif principal["reachable"]:
        serving = principal["name"]
    elif secours["reachable"]:
        serving = secours["name"]
    else:
        serving = None
    return {"principal": principal, "secours": secours,
            "serving": serving, "answered_by": me["name"]}


def apply_dump(data):
    with Session(engine()) as s:
        for u in data.get("users", []):
            existing = s.scalar(select(User).where(User.username == u["username"]))
            if existing is None:
                nu = User(username=u["username"], password_hash=u.get("password_hash"))
                s.add(nu)
                s.flush()
                s.add(Account(user_id=nu.id, balance=0, currency="EUR"))
            elif u.get("password_hash"):
                existing.password_hash = u["password_hash"]
        s.flush()
        for a in data.get("accounts", []):
            usr = s.scalar(select(User).where(User.username == a["username"]))
            if usr is None:
                continue
            acc = s.scalar(select(Account).where(Account.user_id == usr.id))
            if acc is None:
                s.add(Account(user_id=usr.id, balance=a["balance"], savings=a.get("savings", 0),
                              currency=a.get("currency", "EUR")))
            else:
                acc.balance = a["balance"]
                acc.savings = a.get("savings", float(acc.savings))
        for t in data.get("transactions", []):
            if not t.get("idem_key"):
                continue
            if s.scalar(select(Transaction).where(Transaction.idem_key == t["idem_key"])) is not None:
                continue
            usr = s.scalar(select(User).where(User.username == t.get("username")))
            acc = s.scalar(select(Account).where(Account.user_id == usr.id)) if usr else None
            if acc is not None:
                s.add(Transaction(account_id=acc.id, amount=t["amount"], type=t["type"],
                                  recipient=t.get("recipient"), status=t.get("status", "completed"),
                                  idem_key=t["idem_key"]))
        s.commit()


def push_state_to_primary():
    """Pousse l'état courant du secours vers le principal qui revient (failback)."""
    try:
        data = _local_dump()
        r = requests.post(f"{PEER_API_URL}/repl/restore", json=data,
                          headers={"X-Repl-Token": REPL_TOKEN}, timeout=8)
        return r.status_code == 200
    except Exception:  # noqa: BLE001
        return False


def replicate_loop():
    """Secours : boucle de haute disponibilité (bascule ET retour automatiques).

    - Mode réplication : copie l'état du principal toutes les REPL_INTERVAL s.
      Après FAIL_PROMOTE échecs consécutifs -> PROMOTION (le secours devient actif).
    - Mode promu : surveille le retour du principal. Dès qu'il répond de nouveau
      (FAILBACK_CONFIRM cycles), le secours lui REJOUE son état (aucune transaction
      perdue) puis REPASSE en réplication -> le principal reprend la main.
    """
    ha_event("Secours en ligne — réplication depuis le principal", "info")
    recover = 0
    while True:
        time.sleep(REPL_INTERVAL)
        if not repl_state["promoted"]:
            try:
                r = requests.get(f"{PEER_API_URL}/repl/dump",
                                 headers={"X-Repl-Token": REPL_TOKEN}, timeout=4)
                if r.status_code == 200:
                    apply_dump(r.json())
                    repl_state["last_sync"] = time.time()
                    if repl_state["fails"] > 0:
                        ha_event("Principal de nouveau joignable — réplication rétablie", "success")
                    repl_state["fails"] = 0
                else:
                    repl_state["fails"] += 1
            except Exception:  # noqa: BLE001
                repl_state["fails"] += 1
            if repl_state["fails"] >= FAIL_PROMOTE and not repl_state["promoted"]:
                repl_state["promoted"] = True
                repl_state["role"] = "primary (promu)"
                recover = 0
                ha_event(f"Principal injoignable ({FAIL_PROMOTE} échecs) — PROMOTION : "
                         f"le secours devient actif", "alert")
        else:
            healthy = False
            try:
                r = requests.get(f"{PEER_API_URL}/health", timeout=3)
                healthy = (r.status_code == 200)
            except Exception:  # noqa: BLE001
                healthy = False
            if healthy:
                recover += 1
                if recover == 1:
                    ha_event("Principal détecté de nouveau en ligne — préparation du retour…", "info")
                if recover >= FAILBACK_CONFIRM:
                    if push_state_to_primary():
                        ha_event("État répliqué vers le principal (aucune transaction perdue)", "action")
                        repl_state["promoted"] = False
                        repl_state["role"] = ROLE
                        repl_state["fails"] = 0
                        recover = 0
                        ha_event("RETOUR : le principal reprend la main, le secours "
                                 "repasse en réplication", "success")
                    else:
                        ha_event("Réconciliation échouée — le secours reste actif, nouvel essai", "error")
                        recover = 0
            else:
                recover = 0


Instrumentator().instrument(app).expose(app)
