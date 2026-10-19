"""Service d'authentification — Resilience-Alpha.

Gère les comptes utilisateurs fictifs et émet des JWT (HS256) signés avec un
secret partagé avec l'API. Expose /metrics pour Prometheus.
"""
import os
import re
import time
import datetime as dt

import bcrypt
import jwt
from fastapi import FastAPI, HTTPException, Header, Body
from pydantic import BaseModel
from prometheus_client import Counter
from sqlalchemy import create_engine, Integer, String, Numeric, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from prometheus_fastapi_instrumentator import Instrumentator

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALG = "HS256"
JWT_TTL_MIN = int(os.environ.get("JWT_TTL_MIN", "60"))
DEMO_USER = os.environ.get("DEMO_USER", "alice")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "password123")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "orchestrator-admin-token")
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "internal-trusted-token")

import threading as _threading

# Mode "bouclier" : load-shedding activable par le moteur de remédiation.
# Quand il est actif, les requêtes /login NON internes au-delà d'un débit sont
# rejetées immédiatement (429) AVANT le calcul bcrypt coûteux => l'auth tient.
_protect = {"enabled": False, "rate": 8.0}
_bucket = {"tokens": 0.0, "last": time.time()}
_plock = _threading.Lock()


def _allow_request() -> bool:
    with _plock:
        if not _protect["enabled"]:
            return True
        now = time.time()
        _bucket["tokens"] = min(_protect["rate"], _bucket["tokens"] + (now - _bucket["last"]) * _protect["rate"])
        _bucket["last"] = now
        if _bucket["tokens"] >= 1:
            _bucket["tokens"] -= 1
            return True
        return False


# --- WAF applicatif : inspection des entrées (signatures type OWASP) ---
WAF_BLOCKED = Counter("waf_blocked_total", "Requêtes bloquées par le WAF applicatif", ["rule"])
WAF_PATTERNS = [
    ("sqli_or_and", re.compile(r"(?i)('|%27)\s*(or|and)\s")),
    ("sqli_union", re.compile(r"(?i)\bunion\b.*\bselect\b")),
    ("sqli_tautology", re.compile(r"(?i)\bor\b\s+['\"]?\d+['\"]?\s*=\s*['\"]?\d+")),
    ("sqli_drop", re.compile(r"(?i)\bdrop\b\s+\btable\b")),
    ("sqli_insert", re.compile(r"(?i)\binsert\b\s+\binto\b")),
    ("sql_comment", re.compile(r"(--|#|/\*)")),
    ("xss_script", re.compile(r"(?i)<script")),
]


def waf_scan(source: str, **fields):
    """Bloque (403) si une valeur correspond à une signature d'attaque."""
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
    password_hash: Mapped[str] = mapped_column(String(255))


class Account(Base):
    __tablename__ = "accounts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    balance: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    currency: Mapped[str] = mapped_column(String(3), default="EUR")


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


def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()


def check_pw(pw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(pw.encode(), hashed.encode())
    except Exception:  # noqa: BLE001
        return False


app = FastAPI(title="Resilience-Alpha — Auth")


class Creds(BaseModel):
    username: str
    password: str


@app.on_event("startup")
def startup():
    wait_for_db()
    # Les tables sont créées par db/init.sql ; on sème les comptes clients de démo.
    seeds = [(DEMO_USER, DEMO_PASSWORD), ("bob", DEMO_PASSWORD)]
    with Session(engine()) as s:
        for username, pw in seeds:
            if s.scalar(select(User).where(User.username == username)) is None:
                u = User(username=username, password_hash=hash_pw(pw))
                s.add(u)
                s.flush()
                s.add(Account(user_id=u.id, balance=1000, currency="EUR"))
        s.commit()


@app.get("/health")
def health():
    return {"status": "ok", "service": "auth"}


@app.post("/register")
def register(c: Creds):
    with Session(engine()) as s:
        if s.scalar(select(User).where(User.username == c.username)):
            raise HTTPException(409, "username already exists")
        u = User(username=c.username, password_hash=hash_pw(c.password))
        s.add(u)
        s.flush()
        s.add(Account(user_id=u.id, balance=1000, currency="EUR"))
        s.commit()
    return {"status": "created", "username": c.username}


@app.get("/protect")
def protect_status():
    return {"protection": _protect}


@app.post("/admin/protect")
def admin_protect(body: dict = Body(...), x_admin_token: str = Header(default=None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "forbidden")
    _protect["enabled"] = bool(body.get("enabled", False))
    if "rate" in body:
        _protect["rate"] = float(body["rate"])
    return {"protection": _protect}


@app.post("/login")
def login(c: Creds, x_internal_token: str = Header(default=None)):
    # WAF : inspection des entrées avant tout traitement.
    waf_scan("auth/login", username=c.username, password=c.password)
    # Les clients internes de confiance (canari, trafic légitime) ne sont jamais
    # délestés ; le trafic externe est limité quand le bouclier est actif.
    if x_internal_token != INTERNAL_TOKEN and not _allow_request():
        raise HTTPException(429, "service protégé (débit limité)")
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == c.username))
        if u is None or not check_pw(c.password, u.password_hash):
            raise HTTPException(401, "invalid credentials")
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=JWT_TTL_MIN)
    token = jwt.encode({"sub": c.username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)
    return {"access_token": token, "token_type": "bearer"}


Instrumentator().instrument(app).expose(app)
