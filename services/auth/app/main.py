"""Service d'authentification — Resilience-Alpha.

Gère les comptes utilisateurs fictifs et émet des JWT (HS256) signés avec un
secret partagé avec l'API. Expose /metrics pour Prometheus.
"""
import os
import time
import datetime as dt

import bcrypt
import jwt
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from sqlalchemy import create_engine, Integer, String, Numeric, ForeignKey, select
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from prometheus_fastapi_instrumentator import Instrumentator

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALG = "HS256"
JWT_TTL_MIN = int(os.environ.get("JWT_TTL_MIN", "60"))
DEMO_USER = os.environ.get("DEMO_USER", "alice")
DEMO_PASSWORD = os.environ.get("DEMO_PASSWORD", "password123")


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
    # Les tables sont créées par db/init.sql ; on sème le compte de démo.
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == DEMO_USER))
        if u is None:
            u = User(username=DEMO_USER, password_hash=hash_pw(DEMO_PASSWORD))
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


@app.post("/login")
def login(c: Creds):
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == c.username))
        if u is None or not check_pw(c.password, u.password_hash):
            raise HTTPException(401, "invalid credentials")
    exp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=JWT_TTL_MIN)
    token = jwt.encode({"sub": c.username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)
    return {"access_token": token, "token_type": "bearer"}


Instrumentator().instrument(app).expose(app)
