"""API métier de paiement — Resilience-Alpha.

Traite des transactions fictives. Vérifie les JWT émis par le service auth
(secret partagé). Expose /metrics pour Prometheus (utilisé plus tard par la
détection ML et la supervision).
"""
import os
import re
import time
import json
import asyncio
import threading
import datetime as dt

import jwt
import requests
from fastapi import FastAPI, HTTPException, Depends, Header, Body, WebSocket, WebSocketDisconnect
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
GAME_HEIST_MAX = float(os.environ.get("GAME_HEIST_MAX", "120"))   # plafond PAR retrait (€)
GAME_LOOT_CAP = float(os.environ.get("GAME_LOOT_CAP", "400"))     # plafond CUMULÉ du butin (€)
GAME_RECON_FOR_HEIST = int(os.environ.get("GAME_RECON_FOR_HEIST", "3"))  # recon requis avant vol
GAME_SEED_SAVINGS = float(os.environ.get("GAME_SEED_SAVINGS", "300"))    # livret initial de la victime
# Dégradé/503 des endpoints métier lors d'une bascule (nginx proxy_next_upstream
# -> secours). OFF par défaut (démo mono-machine stable) ; passer GAME_DEGRADE=1
# sur un montage 2 PC avec un vrai secours pour une bascule réseau réelle.
GAME_DEGRADE = os.environ.get("GAME_DEGRADE", "0") == "1"

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
}
game_lock = threading.Lock()
degraded = {"on": False}  # bascule : endpoints métier en 503 (gated par GAME_DEGRADE)

GAME_RECON = Counter("game_recon_total", "Sondes de reconnaissance (jeu)")
GAME_HEIST = Counter("game_heist_total", "Tentatives de retrait réussies (jeu)")
GAME_HEIST_AMT = Counter("game_heist_amount_total", "Montant exfiltré cumulé (jeu)")
GAME_LOOT = Gauge("game_loot_current", "Butin courant détenu par l'attaquant (jeu)")
GAME_BLOCKED = Gauge("game_blocked", "1 si l'attaquant est bloqué par l'IA (jeu)")


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
        return {
            "principal": {"balance": float(acc.savings), "rate": savings_cfg["rate"]},
            "livrets": [{"id": lv.id, "name": lv.name, "balance": float(lv.balance),
                         "rate": float(lv.rate), "level": lv.level} for lv in extras],
            "interval": savings_cfg["interval"],
        }


@app.post("/livrets")
def create_livret(body: LivretIn, user: str = Depends(current_user)):
    # P0 : création libre (P1 shop ajoutera le coût exponentiel). Taux = taux de base.
    with Session(engine()) as s:
        u = _user_or_404(s, user)
        n = s.scalar(select(func.count()).select_from(Livret).where(Livret.user_id == u.id)) or 0
        name = (body.name or f"Livret {int(n) + 2}")[:40]
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
                if rate > 0:
                    for a in s.scalars(select(Account).where(Account.savings > 0)).all():
                        interest = round(float(a.savings) * rate, 2)
                        if interest > 0:
                            a.savings = float(a.savings) + interest
                            touched = True
                for lv in s.scalars(select(Livret).where(Livret.balance > 0, Livret.rate > 0)).all():
                    interest = round(float(lv.balance) * float(lv.rate), 2)
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
    return g


@app.get("/game/state")
def game_state_public():
    """État du jeu lu en direct par la console attaquant (toujours disponible)."""
    GAME_BLOCKED.set(1 if _cooldown_remaining() > 0 else 0)
    return _game_public()


class TargetIn(BaseModel):
    username: str


@app.post("/game/target")
def game_target(body: TargetIn):
    """Choix de la CIBLE courante (l'attaquant vise qui il veut). On vérifie que
    c'est bien un client de rôle 'client'. Changer de cible repart d'une recon
    vierge (les infos fuitées valaient pour l'ancienne cible) ; le butin est conservé."""
    name = (body.username or "").strip()
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == name))
        if u is None or (u.role or "client") != "client":
            raise HTTPException(400, "cible invalide — choisir un compte client existant")
    with game_lock:
        changed = name != game_state["victim"]
        game_state["victim"] = name
        if changed:
            game_state["recon_count"] = 0
            game_state["intel"] = []
    print(f"[GAME] TARGET -> {name}", flush=True)
    return {"ok": True, "victim": name, **_game_public()}


@app.post("/game/recon")
def game_recon():
    """Sonde de reconnaissance : fuite progressive d'infos sur la cible (par
    conception, pour le jeu). Instrumentée (compteur Prometheus + log) pour que
    l'IA puisse repérer un motif d'énumération."""
    if _cooldown_remaining() > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {_cooldown_remaining()}s")
    GAME_RECON.inc()
    with Session(engine()) as s:
        clients = s.execute(
            select(User.username, Account.balance, Account.savings)
            .join(Account, Account.user_id == User.id)
            .where(User.role == "client").order_by(Account.balance.desc())
        ).all()
    victim = game_state["victim"]
    vrow = next((r for r in clients if r.username == victim), (clients[0] if clients else None))
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
            has = float(vrow.savings) > 0
            item = (f"Cible « {vrow.username} » possède un LIVRET d'épargne ({_bucket(float(vrow.savings))})."
                    if has else f"Cible « {vrow.username} » : pas de livret d'épargne détecté.")
        else:
            item = "Infos suffisantes — un retrait ciblé et PLAFONNÉ est possible."
        if item not in game_state["intel"]:
            game_state["intel"].append(item)
        game_state["intel"] = game_state["intel"][-8:]
        count = game_state["recon_count"]
    print(f"[GAME] recon #{count} victim={victim} -> {item}", flush=True)
    return {"ok": True, "recon_count": count, "leaked": item,
            "ready_to_heist": count >= GAME_RECON_FOR_HEIST, **_game_public()}


class HeistIn(BaseModel):
    amount: float | None = None
    source: str | None = "courant"   # courant | epargne


@app.post("/game/heist")
def game_heist(body: HeistIn):
    """Vol PLAFONNÉ sur la cible : retrait atomique (FOR UPDATE), jamais négatif,
    plafonné par coup (GAME_HEIST_MAX) et en cumulé (GAME_LOOT_CAP). Tracé."""
    if _cooldown_remaining() > 0:
        raise HTTPException(403, f"attaquant bloqué — cooldown {_cooldown_remaining()}s")
    with game_lock:
        if game_state["recon_count"] < GAME_RECON_FOR_HEIST:
            raise HTTPException(400, f"reconnaissance insuffisante "
                                     f"({game_state['recon_count']}/{GAME_RECON_FOR_HEIST})")
        cap_left = GAME_LOOT_CAP - game_state["loot"] - game_state["loot_neutralized"]
    if cap_left <= 0:
        raise HTTPException(400, "plafond de butin atteint — trop risqué d'insister")
    src = (body.source or "courant").lower()
    want = body.amount if (body.amount and body.amount > 0) else GAME_HEIST_MAX
    want = min(want, GAME_HEIST_MAX, cap_left)
    victim = game_state["victim"]
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == victim))
        acc = s.scalar(select(Account).where(Account.user_id == u.id).with_for_update()) if u else None
        if acc is None:
            raise HTTPException(404, "cible introuvable")
        if src == "epargne":
            avail = float(acc.savings)
            stolen = round(min(want, avail), 2)
            if stolen <= 0:
                raise HTTPException(402, "livret vide — rien à exfiltrer")
            acc.savings = float(acc.savings) - stolen
            label = "⚠ EXFILTRATION LIVRET (jeu)"
        else:
            avail = float(acc.balance)
            stolen = round(min(want, avail), 2)
            if stolen <= 0:
                raise HTTPException(402, "compte vide — rien à exfiltrer")
            acc.balance = float(acc.balance) - stolen
            label = "⚠ EXFILTRATION (jeu)"
        s.add(Transaction(account_id=acc.id, amount=stolen, type="debit",
                          recipient=label, status="completed"))
        s.commit()
    with game_lock:
        game_state["loot"] = round(game_state["loot"] + stolen, 2)
        game_state["exfiltrated_total"] = round(game_state["exfiltrated_total"] + stolen, 2)
        game_state["heist_count"] += 1
        loot = game_state["loot"]
    GAME_HEIST.inc()
    GAME_HEIST_AMT.inc(stolen)
    GAME_LOOT.set(loot)
    print(f"[GAME] HEIST victim={victim} source={src} stolen={stolen} loot={loot}", flush=True)
    ws_manager.publish({"type": "tx", "from": victim, "to": "⚠ INCONNU", "amount": stolen, "op": "heist"})
    return {"ok": True, "stolen": stolen, "source": src, "loot": loot, **_game_public()}


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
                           "intel": [], "discovered": [], "blocked_until": 0.0, "block_reason": ""})
    GAME_LOOT.set(0)
    GAME_BLOCKED.set(0)
    return _game_public()


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
