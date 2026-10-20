"""Démo de paiement MINIMALE et AUTONOME — sans aucun add-on de jeu.

Petite « vraie » application métier à protéger pour la démo du workshop : login
factice, consultation de solde, paiement, historique, et une page web simple.
Tout est en mémoire (aucune base), fictif et pédagogique. Cette app n'embarque
AUCUNE sécurité : c'est Resilience Guard, posé devant, qui la protège.
"""
import os
import secrets
import datetime

from fastapi import FastAPI, HTTPException, Header, Body
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

# Comptes de démonstration (en mémoire).
USERS = {
    "alice": {"password": "demo123", "balance": 1000.0},
    "bob": {"password": "demo123", "balance": 1000.0},
}
TOKENS = {}          # token -> username
TX = {}              # username -> [transactions]

app = FastAPI(title="Démo Paiement — app métier à protéger")


class Creds(BaseModel):
    username: str
    password: str


class Pay(BaseModel):
    amount: float
    recipient: str


def current_user(authorization: str | None) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "authentification requise")
    user = TOKENS.get(authorization[7:])
    if not user:
        raise HTTPException(401, "session invalide")
    return user


@app.get("/health")
def health():
    return {"status": "ok", "app": "paiement"}


@app.post("/login")
def login(creds: Creds):
    u = USERS.get(creds.username)
    if not u or u["password"] != creds.password:
        raise HTTPException(401, "identifiants invalides")
    token = secrets.token_urlsafe(16)
    TOKENS[token] = creds.username
    return {"access_token": token, "username": creds.username}


@app.get("/balance")
def balance(authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    return {"username": user, "balance": round(USERS[user]["balance"], 2)}


@app.post("/pay")
def pay(body: Pay, authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    if body.amount <= 0:
        raise HTTPException(400, "montant invalide")
    if body.amount > USERS[user]["balance"]:
        raise HTTPException(400, "solde insuffisant")
    USERS[user]["balance"] -= body.amount
    rec = {"t": datetime.datetime.now().strftime("%H:%M:%S"),
           "amount": round(body.amount, 2), "recipient": body.recipient}
    TX.setdefault(user, []).insert(0, rec)
    TX[user] = TX[user][:20]
    return {"ok": True, "balance": round(USERS[user]["balance"], 2), "transaction": rec}


@app.get("/transactions")
def transactions(authorization: str | None = Header(default=None)):
    user = current_user(authorization)
    return {"transactions": TX.get(user, [])}


@app.get("/", response_class=HTMLResponse)
def index():
    return PAGE


PAGE = """<!doctype html>
<html lang="fr"><head><meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>PayDemo — Espace client</title>
<style>
  :root { --bg:#0e1526; --card:#162038; --ink:#e7ecf7; --muted:#90a0c0; --accent:#2f9e7a;
    --line:#243150; --bad:#e5604d; }
  *{box-sizing:border-box} body{margin:0;background:var(--bg);color:var(--ink);
    font-family:system-ui,-apple-system,Segoe UI,Roboto,sans-serif}
  .wrap{max-width:560px;margin:0 auto;padding:34px 18px}
  h1{font-size:22px;margin:0 0 4px}.sub{color:var(--muted);font-size:13px;margin-bottom:22px}
  .card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px;margin-bottom:16px}
  label{display:block;font-size:12px;color:var(--muted);margin:10px 0 4px;text-transform:uppercase;letter-spacing:.06em}
  input{width:100%;background:#0f1930;border:1px solid var(--line);color:var(--ink);
    border-radius:9px;padding:11px 12px;font-size:15px}
  button{margin-top:16px;width:100%;background:var(--accent);color:#fff;border:0;border-radius:9px;
    padding:12px;font-weight:700;font-size:15px;cursor:pointer}
  button:disabled{opacity:.5}
  .balance{font-size:34px;font-weight:800}.balance span{font-size:16px;color:var(--muted)}
  .row{display:flex;gap:10px}.row>div{flex:1}
  .msg{font-size:13px;margin-top:10px;min-height:18px}.err{color:var(--bad)}.ok{color:var(--accent)}
  .tx{font-size:13px;border-top:1px solid var(--line);padding:7px 0;display:flex;gap:10px}
  .tx .ts{color:var(--muted);font-variant-numeric:tabular-nums}
  .hint{color:var(--muted);font-size:12px;margin-top:8px}
  .hidden{display:none}
</style></head>
<body><div class="wrap">
  <h1>PayDemo</h1><div class="sub">Espace client — application métier de démonstration</div>

  <div class="card" id="login-card">
    <label>Identifiant</label><input id="u" value="alice" autocomplete="username" />
    <label>Mot de passe</label><input id="p" type="password" value="demo123" autocomplete="current-password" />
    <button id="login-btn">Se connecter</button>
    <div class="msg err" id="login-msg"></div>
    <div class="hint">Comptes de démo : alice / bob — mot de passe <code>demo123</code>.</div>
  </div>

  <div class="card hidden" id="app-card">
    <label>Solde du compte</label>
    <div class="balance" id="bal">— <span>EUR</span></div>
    <label style="margin-top:18px">Nouveau paiement</label>
    <div class="row">
      <div><input id="amount" type="number" placeholder="Montant" value="25" /></div>
      <div><input id="recipient" placeholder="Bénéficiaire" value="EDF" /></div>
    </div>
    <button id="pay-btn">Payer</button>
    <div class="msg" id="pay-msg"></div>
    <div id="tx" style="margin-top:14px"></div>
    <button id="logout-btn" style="background:#2a3550;margin-top:18px">Se déconnecter</button>
  </div>
</div>
<script>
let token = null;
const $ = id => document.getElementById(id);
async function api(path, opts={}) {
  const h = {"Content-Type":"application/json", ...(opts.headers||{})};
  if (token) h["Authorization"] = "Bearer "+token;
  const r = await fetch(path, {...opts, headers:h});
  const j = await r.json().catch(()=>({detail:r.statusText}));
  if (!r.ok) throw new Error(j.detail || ("HTTP "+r.status));
  return j;
}
async function refresh() {
  const b = await api("/balance"); $("bal").innerHTML = b.balance.toFixed(2)+' <span>EUR</span>';
  const t = await api("/transactions");
  $("tx").innerHTML = (t.transactions||[]).map(x =>
    `<div class="tx"><span class="ts">${x.ts}</span><span>&rarr; ${x.recipient}</span><span style="margin-left:auto">-${x.amount.toFixed(2)} €</span></div>`
  ).join("") || '<div class="hint">Aucun paiement pour le moment.</div>';
}
$("login-btn").addEventListener("click", async () => {
  $("login-msg").textContent = "";
  try {
    const r = await api("/login", {method:"POST", body:JSON.stringify({username:$("u").value, password:$("p").value})});
    token = r.access_token; $("login-card").classList.add("hidden"); $("app-card").classList.remove("hidden");
    await refresh();
  } catch(e){ $("login-msg").textContent = e.message; }
});
$("pay-btn").addEventListener("click", async () => {
  const m = $("pay-msg"); m.className="msg"; m.textContent="";
  try {
    const r = await api("/pay", {method:"POST", body:JSON.stringify({amount:parseFloat($("amount").value), recipient:$("recipient").value})});
    m.className="msg ok"; m.textContent = "Paiement de "+r.transaction.amount.toFixed(2)+" € à "+r.transaction.recipient+" effectué.";
    await refresh();
  } catch(e){ m.className="msg err"; m.textContent = e.message; }
});
$("logout-btn").addEventListener("click", () => {
  token=null; $("app-card").classList.add("hidden"); $("login-card").classList.remove("hidden");
});
</script>
</body></html>"""
