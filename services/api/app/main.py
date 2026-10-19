"""API métier de paiement — Resilience-Alpha.

Traite des transactions fictives. Vérifie les JWT émis par le service auth
(secret partagé). Expose /metrics pour Prometheus (utilisé plus tard par la
détection ML et la supervision).
"""
import os
import time
import datetime as dt

import jwt
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from sqlalchemy import (
    create_engine, Integer, String, Numeric, ForeignKey, DateTime, func, select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, Session
from prometheus_fastapi_instrumentator import Instrumentator

DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ.get("JWT_SECRET", "dev-secret")
JWT_ALG = "HS256"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)


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
    recipient: str | None = None


@app.on_event("startup")
def startup():
    wait_for_db()


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
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    with Session(engine()) as s:
        u = s.scalar(select(User).where(User.username == user))
        acc = s.scalar(select(Account).where(Account.user_id == u.id)) if u else None
        if acc is None:
            raise HTTPException(404, "account not found")
        if float(acc.balance) < body.amount:
            tx = Transaction(account_id=acc.id, amount=body.amount, type="debit",
                             recipient=body.recipient, status="refused")
            s.add(tx)
            s.commit()
            raise HTTPException(402, "insufficient funds")
        acc.balance = float(acc.balance) - body.amount
        tx = Transaction(account_id=acc.id, amount=body.amount, type="debit",
                         recipient=body.recipient, status="completed")
        s.add(tx)
        s.commit()
        return {"id": tx.id, "status": "completed", "amount": body.amount,
                "new_balance": float(acc.balance)}


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


Instrumentator().instrument(app).expose(app)
