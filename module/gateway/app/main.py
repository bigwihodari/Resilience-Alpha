"""Passerelle Resilience Guard — reverse-proxy défensif « plug-and-protect ».

Se place DEVANT n'importe quelle application web (`PROTECTED_UPSTREAM`) sans toucher
à son code. Pour chaque requête :

  1. WAF applicatif (signatures type OWASP : SQLi / XSS) sur le chemin, la query et
     le corps  → requête malveillante bloquée en 403 (+ `waf_blocked_total`).
  2. Load-shedding : si le bouclier anti-DoS est actif (`POST /admin/protect`), les
     requêtes au-delà d'un débit sont rejetées en 429 (token bucket) AVANT d'atteindre
     l'app → l'app protégée tient sous la charge.
  3. Proxy vers `PROTECTED_UPSTREAM` (httpx), méthode / headers / corps conservés.
  4. Mesure de la latence et du statut.

Expose `/metrics` (Prometheus) avec EXACTEMENT les mêmes noms que la démo d'origine
(`http_requests_total`, `http_request_duration_seconds_bucket`, `waf_blocked_total`)
pour que detector / prometheus / grafana fonctionnent sans changement, et `/health`.
Aucune dépendance à l'application protégée.
"""
import os
import re
import time
import threading

import httpx
from fastapi import FastAPI, Request, Response, Body, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# --- Configuration (tout par variables d'environnement, aucune valeur « jeu ») ---
PROTECTED_UPSTREAM = os.environ.get("PROTECTED_UPSTREAM", "http://host.docker.internal:8000").rstrip("/")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "orchestrator-admin-token")
# Token interne : le canari de l'orchestrateur l'envoie pour ne pas être délesté par le bouclier.
INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "internal-trusted-token")
# Identité du nœud (haute disponibilité) : « primary » ou « backup ». Exposée dans
# /health et dans l'en-tête X-RG-Node de chaque réponse pour que le cockpit sache
# quel nœud sert réellement le trafic (et détecte une bascule).
NODE_ID = os.environ.get("NODE_ID", "primary")
UPSTREAM_TIMEOUT = float(os.environ.get("UPSTREAM_TIMEOUT", "15"))
DEFAULT_SHED_RATE = float(os.environ.get("SHED_RATE", "8.0"))

# --- Métriques (mêmes noms que l'app de démo : instrumentator FastAPI par défaut) ---
HTTP_REQUESTS = Counter(
    "http_requests_total", "Nombre de requêtes HTTP servies par la passerelle",
    ["method", "status"],
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds", "Latence des requêtes servies par la passerelle",
    ["method"],
)
WAF_BLOCKED = Counter("waf_blocked_total", "Requêtes bloquées par le WAF applicatif", ["rule"])

# --- WAF applicatif (signatures type OWASP) — repris de services/api + services/auth ---
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
        if not isinstance(value, str) or not value:
            continue
        for rule, rx in WAF_PATTERNS:
            if rx.search(value):
                WAF_BLOCKED.labels(rule=rule).inc()
                print(f"[WAF] BLOCK rule={rule} source={source} field={name} value={value[:120]!r}", flush=True)
                raise HTTPException(403, "requête bloquée par le WAF")


# --- Bouclier anti-DoS (load-shedding) : token bucket, comme l'auth d'origine ---
_protect = {"enabled": False, "rate": DEFAULT_SHED_RATE}
_bucket = {"tokens": 0.0, "last": time.time()}
_plock = threading.Lock()


def _allow_request() -> bool:
    """False si le bouclier est actif ET le débit dépasse la capacité (requête à délester)."""
    with _plock:
        if not _protect["enabled"]:
            return True
        now = time.time()
        rate = _protect["rate"]
        _bucket["tokens"] = min(rate, _bucket["tokens"] + (now - _bucket["last"]) * rate)
        _bucket["last"] = now
        if _bucket["tokens"] >= 1:
            _bucket["tokens"] -= 1
            return True
        return False


# En-têtes à ne pas réémettre tels quels vers l'amont / le client (hop-by-hop).
# `content-encoding` est retiré car httpx décode déjà le corps (sinon le client
# tenterait de « dé-gziper » un contenu déjà décompressé).
_HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "host", "content-length",
    "content-encoding",
}

app = FastAPI(title="Resilience Guard — Passerelle (WAF + proxy + métriques)")
_client: httpx.AsyncClient | None = None


@app.middleware("http")
async def _tag_node(request: Request, call_next):
    """Marque chaque réponse avec l'identité du nœud (HA : qui a servi la requête)."""
    response = await call_next(request)
    response.headers["X-RG-Node"] = NODE_ID
    return response


@app.on_event("startup")
async def _startup():
    global _client
    _client = httpx.AsyncClient(timeout=UPSTREAM_TIMEOUT, follow_redirects=False)
    print(f"[gateway] amont protégé = {PROTECTED_UPSTREAM}", flush=True)


@app.on_event("shutdown")
async def _shutdown():
    if _client is not None:
        await _client.aclose()


# --- Endpoints de gestion de la passerelle (non proxifiés) ---
@app.get("/health")
def health():
    return {"status": "ok", "service": "gateway", "node": NODE_ID,
            "upstream": PROTECTED_UPSTREAM, "shield": _protect["enabled"]}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/admin/protect")
def protect_status():
    return {"protection": dict(_protect)}


@app.post("/admin/protect")
def admin_protect(body: dict = Body(...), x_admin_token: str = Header(default=None)):
    """Active/désactive le bouclier de load-shedding. Protégé par ADMIN_TOKEN
    (même mécanisme que l'API d'administration scoped de l'orchestrateur)."""
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(403, "token d'administration invalide")
    with _plock:
        _protect["enabled"] = bool(body.get("enabled", False))
        if "rate" in body:
            _protect["rate"] = float(body["rate"])
    print(f"[gateway] bouclier -> {_protect}", flush=True)
    return {"protection": dict(_protect)}


def _record(method: str, status_code: int, elapsed: float):
    HTTP_REQUESTS.labels(method=method, status=f"{status_code // 100}xx").inc()
    HTTP_LATENCY.labels(method=method).observe(elapsed)


# --- Proxy générique : toute autre requête traverse WAF + bouclier puis l'amont ---
@app.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
)
async def proxy(full_path: str, request: Request):
    method = request.method
    t0 = time.time()

    # (1) WAF : chemin + chaque paramètre de query + corps brut.
    try:
        waf_scan("path", path="/" + full_path)
        for k, v in request.query_params.multi_items():
            waf_scan("query", **{k: v})
        raw = await request.body()
        if raw:
            try:
                waf_scan("body", body=raw.decode("utf-8", "ignore"))
            except Exception:  # noqa: BLE001
                pass
    except HTTPException as exc:
        _record(method, exc.status_code, time.time() - t0)
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)

    # (2) Load-shedding si le bouclier est actif (sauf requête interne : canari).
    is_internal = request.headers.get("x-internal-token") == INTERNAL_TOKEN
    if not is_internal and not _allow_request():
        _record(method, 429, time.time() - t0)
        return JSONResponse(
            {"detail": "service protégé (bouclier anti-DoS actif) — réessayez plus tard"},
            status_code=429, headers={"Retry-After": "1"},
        )

    # (3) Proxy vers l'amont.
    url = f"{PROTECTED_UPSTREAM}/{full_path}"
    fwd_headers = {k: v for k, v in request.headers.items() if k.lower() not in _HOP_BY_HOP}
    fwd_headers["X-Forwarded-Host"] = request.headers.get("host", "")
    fwd_headers["X-Forwarded-For"] = request.client.host if request.client else ""
    try:
        upstream = await _client.request(
            method, url, params=request.query_params.multi_items(),
            headers=fwd_headers, content=raw,
        )
    except Exception as e:  # noqa: BLE001 — amont injoignable
        _record(method, 502, time.time() - t0)
        return JSONResponse({"detail": f"amont injoignable: {e}"}, status_code=502)

    # (4) Mesure + réémission de la réponse.
    _record(method, upstream.status_code, time.time() - t0)
    resp_headers = {k: v for k, v in upstream.headers.items() if k.lower() not in _HOP_BY_HOP}
    return Response(content=upstream.content, status_code=upstream.status_code,
                    headers=resp_headers,
                    media_type=upstream.headers.get("content-type"))
