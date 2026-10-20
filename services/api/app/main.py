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
from prometheus_client import Counter

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
SAVINGS_RATE = float(os.environ.get("SAVINGS_RATE", "0.01"))       # 1% par cycle (demo)
SAVINGS_INTERVAL = float(os.environ.get("SAVINGS_INTERVAL", "30"))  # secondes
FAIL_PROMOTE = int(os.environ.get("FAIL_PROMOTE", "3"))       # échecs avant promotion du secours
FAILBACK_CONFIRM = int(os.environ.get("FAILBACK_CONFIRM", "3"))  # cycles OK avant retour au principal
repl_state = {"role": ROLE, "name": HA_NAME, "promoted": ROLE == "primary", "peer": PEER_API_URL,
              "last_sync": None, "fails": 0, "events": []}


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
                "savings_rate": SAVINGS_RATE, "savings_interval": SAVINGS_INTERVAL,
                "currency": acc.currency}


@app.post("/transactions")
def create_transaction(body: TxIn, user: str = Depends(current_user)):
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

        # Destinataire : CLIENT connu -> transfert (crédit) ; sinon marchand externe.
        rec_user = s.scalar(select(User).where(User.username == body.recipient)) if body.recipient else None
        if rec_user is not None and rec_user.id == u.id:
            raise HTTPException(400, "cannot pay yourself")
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
                "rate": SAVINGS_RATE, "interval": SAVINGS_INTERVAL}


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


def savings_interest_loop():
    """Ajoute les intérêts du livret toutes les SAVINGS_INTERVAL s (noeud autoritaire)."""
    while True:
        time.sleep(SAVINGS_INTERVAL)
        if not repl_state.get("promoted") or SAVINGS_RATE <= 0:
            continue
        try:
            touched = False
            with Session(engine()) as s:
                accts = s.scalars(select(Account).where(Account.savings > 0)).all()
                for a in accts:
                    interest = round(float(a.savings) * SAVINGS_RATE, 2)
                    if interest <= 0:
                        continue
                    a.savings = float(a.savings) + interest
                    s.add(Transaction(account_id=a.id, amount=interest, type="credit",
                                      recipient="LIVRET (intérêts)", status="completed"))
                    touched = True
                s.commit()
            if touched:
                ws_manager.publish({"type": "tx", "from": "LIVRET", "to": "", "amount": 0, "op": "interest"})
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
