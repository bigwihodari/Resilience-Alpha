"""Détecteur d'anomalies ML — Resilience-Alpha.

Interroge Prometheus toutes les N secondes, construit un vecteur de features,
apprend la "vie normale" avec un Isolation Forest (pas de seuils codés en dur),
puis publie un score d'anomalie (0..100) et un drapeau, exposés à Prometheus et
via /status (consommés par le cockpit et, plus tard, le moteur de remédiation).
"""
import os
import time
import threading

import numpy as np
import requests
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

PROM = os.environ.get("PROM_URL", "http://prometheus:9090")
INTERVAL = float(os.environ.get("INTERVAL", "5"))
WARMUP = int(os.environ.get("WARMUP_SAMPLES", "30"))
CONTAM = float(os.environ.get("CONTAMINATION", "0.02"))

# Les signaux observés (métriques applicatives réelles, issues de Prometheus).
QUERIES = {
    "req_total": 'sum(rate(http_requests_total[1m]))',
    "req_auth": 'sum(rate(http_requests_total{job="auth"}[1m]))',
    "lat_auth_p95": 'histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="auth"}[1m])) by (le))',
    "r4xx": 'sum(rate(http_requests_total{status="4xx"}[1m]))',
    "r5xx": 'sum(rate(http_requests_total{status="5xx"}[1m]))',
}
FEATURES = list(QUERIES.keys())

ANOM = Gauge("anomaly_score", "Score d'anomalie 0..100")
FLAG = Gauge("anomaly_flag", "1 si anomalie detectee")
TRAINEDG = Gauge("detector_trained", "1 si modele entraine")

state = {
    "trained": False, "score": 0.0, "is_anomaly": False,
    "features": {}, "samples_collected": 0, "warmup": WARMUP,
    "last_update": None, "reason": "initialisation",
}
baseline = []
model = None
scaler = None
mu_df = 0.0          # moyenne du score du modèle sur la normale apprise
sd_df = 1.0          # écart-type du score sur la normale (seuil adaptatif)
Z_FLAG = float(os.environ.get("Z_FLAG", "3.5"))  # nb d'écarts-types => anomalie
lock = threading.Lock()


def q(query: str) -> float:
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=4)
        res = r.json().get("data", {}).get("result", [])
        if res:
            v = float(res[0]["value"][1])
            return v if v == v else 0.0  # écarte NaN
        return 0.0
    except Exception:
        return 0.0


def sample():
    return [q(QUERIES[f]) for f in FEATURES]


def loop():
    global model, scaler, mu_df, sd_df
    # laisse Prometheus accumuler un peu d'historique avant le 1er échantillon
    time.sleep(10)
    while True:
        feats = sample()
        with lock:
            state["features"] = dict(zip(FEATURES, [round(x, 3) for x in feats]))
            state["last_update"] = time.time()
            if not state["trained"]:
                baseline.append(feats)
                state["samples_collected"] = len(baseline)
                state["reason"] = f"apprentissage ({len(baseline)}/{WARMUP})"
                if len(baseline) >= WARMUP:
                    scaler = StandardScaler().fit(baseline)
                    model = IsolationForest(contamination=CONTAM, random_state=42).fit(scaler.transform(baseline))
                    # Calibre le seuil à partir du score du modèle sur la NORMALE apprise.
                    df_base = model.decision_function(scaler.transform(baseline))
                    mu_df = float(np.mean(df_base))
                    sd_df = max(float(np.std(df_base)), 1e-2)
                    state["trained"] = True
                    state["reason"] = "modele entraine"
                    TRAINEDG.set(1)
            else:
                df = float(model.decision_function(scaler.transform([feats]))[0])
                # z > 0 => plus anormal que la normale apprise (score du modèle plus bas)
                z = (mu_df - df) / sd_df
                score = max(0.0, min(100.0, z * 20.0))
                is_anom = z > Z_FLAG
                state["score"] = round(score, 1)
                state["is_anomaly"] = is_anom
                state["reason"] = "anomalie detectee" if is_anom else "normal"
                ANOM.set(score)
                FLAG.set(1 if is_anom else 0)
        time.sleep(INTERVAL)


app = FastAPI(title="Resilience-Alpha — Détecteur ML")


@app.on_event("startup")
def startup():
    threading.Thread(target=loop, daemon=True).start()


@app.get("/health")
def health():
    return {"status": "ok", "service": "detector", "trained": state["trained"]}


@app.get("/status")
def status():
    with lock:
        return dict(state)


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
