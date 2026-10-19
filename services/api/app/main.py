"""API métier de paiement — Resilience-Alpha.

Traite des transactions fictives. Vérifie les JWT émis par le service auth
(secret partagé). Expose /metrics pour Prometheus (utilisé plus tard par la
détection ML et la supervision).
"""
import os
import re
import time
import threading
import datetime as dt

import jwt
import requests
from fastapi import FastAPI, HTTPException, Depends, Header
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
PEER_API_URL = os.environ.get("PEER_API_URL", "")     # backup : URL de l'api du principal
REPL_TOKEN = os.environ.get("REPL_TOKEN", "repl-secret")
REPL_INTERVAL = float(os.environ.get("REPL_INTERVAL", "2"))
repl_state = {"role": ROLE, "promoted": ROLE == "primary", "peer": PEER_API_URL,
              "last_sync": None, "fails": 0}

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


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    balance: Mapped[float] = mapped_column(Numeric(14, 2))
    currency: Mapped[str] = mapped_column(String(3))


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


def current_user(authorization: str = Header(default=None)) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    token = authorization.split(" ", 1)[1]
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
    except Exception:  # noqa: BLE001
        raise HTTPException(401, "invalid token")
    return payload["sub"]


app = FastAPI(title="Resilience-Alpha — Payment API")


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
    if ROLE == "backup" and PEER_API_URL:
        threading.Thread(target=replicate_loop, daemon=True).start()


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
        return {"username": user, "balance": float(acc.balance), "currency": acc.currency}


@app.post("/transactions")
def create_transaction(body: TxIn, user: str = Depends(current_user)):
    waf_scan("api/transactions", recipient=body.recipient or "")
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    key = body.idempotency_key
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        acc = s.scalar(select(Account).where(Account.user_id == u.id)) if u else None
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

        # Destinataire : utilisateur connu -> transfert (crédit) ; sinon marchand externe.
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
        if rec_user is not None:
            rec_acc = s.scalar(select(Account).where(Account.user_id == rec_user.id))
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
        return {"id": tx.id, "status": "completed", "amount": body.amount,
                "recipient": body.recipient, "credited": credited,
                "new_balance": float(acc.balance), "resumed": False}


@app.get("/users")
def list_users(q: str = "", user: str = Depends(current_user)):
    """Annuaire : clients enregistrés disponibles (recherche par nom)."""
    with Session(engine()) as s:
        stmt = select(User.username).where(User.username != user)
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


@app.get("/repl/dump")
def repl_dump(x_repl_token: str = Header(default=None)):
    """État à répliquer (lu par le backup). Protégé par un token interne."""
    if x_repl_token != REPL_TOKEN:
        raise HTTPException(403, "forbidden")
    with Session(engine()) as s:
        users = s.scalars(select(User)).all()
        accounts = s.scalars(select(Account)).all()
        id2name = {u.id: u.username for u in users}
        acc_by_user = {}
        out_accounts = []
        for a in accounts:
            uname = id2name.get(a.user_id)
            acc_by_user[a.id] = uname
            out_accounts.append({"username": uname, "balance": float(a.balance), "currency": a.currency})
        txs = s.scalars(select(Transaction).where(Transaction.idem_key.is_not(None))).all()
        out_tx = [{"idem_key": t.idem_key, "username": acc_by_user.get(t.account_id),
                   "amount": float(t.amount), "type": t.type, "recipient": t.recipient,
                   "status": t.status} for t in txs]
    return {
        "users": [{"username": u.username, "password_hash": u.password_hash} for u in users],
        "accounts": out_accounts,
        "transactions": out_tx,
    }


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
                s.add(Account(user_id=usr.id, balance=a["balance"], currency=a.get("currency", "EUR")))
            else:
                acc.balance = a["balance"]
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


def replicate_loop():
    """Backup : réplique l'état du principal. Après plusieurs échecs consécutifs,
    se promeut (devient autoritaire) et cesse de répliquer pour ne pas écraser ses
    propres transactions post-bascule."""
    print(f"[repl] backup : réplication depuis {PEER_API_URL}", flush=True)
    while True:
        time.sleep(REPL_INTERVAL)
        if repl_state["promoted"]:
            return
        try:
            r = requests.get(f"{PEER_API_URL}/repl/dump", headers={"X-Repl-Token": REPL_TOKEN}, timeout=4)
            if r.status_code == 200:
                apply_dump(r.json())
                repl_state["last_sync"] = time.time()
                repl_state["fails"] = 0
            else:
                repl_state["fails"] += 1
        except Exception:
            repl_state["fails"] += 1
        if repl_state["fails"] >= 3 and not repl_state["promoted"]:
            repl_state["promoted"] = True
            repl_state["role"] = "primary (promu)"
            print("[repl] principal injoignable -> PROMOTION du backup (autoritaire)", flush=True)
            return


Instrumentator().instrument(app).expose(app)
