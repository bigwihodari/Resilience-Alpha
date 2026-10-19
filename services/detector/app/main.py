"""Détecteur d'anomalies ML — Resilience-Alpha.

Interroge Prometheus toutes les N secondes, construit un vecteur de features et
apprend la "vie normale" (pas de seuils codés en dur sur les métriques brutes) :

  1. un Isolation Forest est entraîné sur la normale (modèle d'anomalie) ;
  2. on apprend aussi la distribution normale (moyenne/écart-type par feature) et
     on mesure l'écart courant par une distance standardisée (Mahalanobis
     diagonale). Cette distance déclenche de façon fiable sur les gros écarts.

Le score (0..100) et le drapeau sont exposés à Prometheus et via /status.
Le modèle est persisté sur disque : pas de ré-apprentissage à chaque redémarrage.
"""
import os
import time
import threading

import numpy as np
import requests
import joblib
from fastapi import FastAPI
from fastapi.responses import Response
from prometheus_client import Gauge, generate_latest, CONTENT_TYPE_LATEST
from sklearn.ensemble import IsolationForest

PROM = os.environ.get("PROM_URL", "http://prometheus:9090")
INTERVAL = float(os.environ.get("INTERVAL", "5"))
WARMUP = int(os.environ.get("WARMUP_SAMPLES", "30"))
CONTAM = float(os.environ.get("CONTAMINATION", "0.02"))
DIST_FLAG = float(os.environ.get("DIST_FLAG", "8"))   # distance (σ) => anomalie
MODEL_PATH = os.environ.get("MODEL_PATH", "/app/model/detector.joblib")

# Features = débits (req/s) : signaux stables et directement comparables.
# (La latence, trop sensible au volume de logins bcrypt, reste visible dans le
#  cockpit via Prometheus mais n'entre pas dans le vecteur du modèle.)
QUERIES = {
    "req_total": 'sum(rate(http_requests_total[1m]))',
    "req_auth": 'sum(rate(http_requests_total{job="auth"}[1m]))',
    "r4xx": 'sum(rate(http_requests_total{status="4xx"}[1m]))',
    "r5xx": 'sum(rate(http_requests_total{status="5xx"}[1m]))',
}
FEATURES = list(QUERIES.keys())

ANOM = Gauge("anomaly_score", "Score d'anomalie 0..100")
FLAG = Gauge("anomaly_flag", "1 si anomalie detectee")
TRAINEDG = Gauge("detector_trained", "1 si modele entraine")

state = {
    "trained": False, "score": 0.0, "is_anomaly": False, "distance": 0.0,
    "features": {}, "samples_collected": 0, "warmup": WARMUP,
    "last_update": None, "reason": "initialisation",
}
baseline = []
model = None          # Isolation Forest
mu = None             # moyenne par feature (normale)
sd = None             # écart-type par feature (normale)
base_d_mean = 0.0     # distance moyenne sur la normale
lock = threading.Lock()


def q(query: str) -> float:
    try:
        r = requests.get(f"{PROM}/api/v1/query", params={"query": query}, timeout=4)
        res = r.json().get("data", {}).get("result", [])
        if res:
            v = float(res[0]["value"][1])
            return v if v == v else 0.0
        return 0.0
    except Exception:
        return 0.0


def sample():
    return [q(QUERIES[f]) for f in FEATURES]


def distance(x):
    """Distance standardisée à la normale apprise (Mahalanobis diagonale)."""
    z = (np.asarray(x) - mu) / sd
    return float(np.sqrt(np.sum(z * z)))


def fit(samples):
    global model, mu, sd, base_d_mean
    arr = np.asarray(samples, dtype=float)
    mu = arr.mean(axis=0)
    sd = arr.std(axis=0)
    # Plancher de bruit adapté au domaine (débits en req/s) : une variation de
    # moins de ~0.5 req/s n'est pas significative. Évite qu'une feature quasi
    # constante à l'entraînement (ex. 4xx=0) ne sur-réagisse au moindre bruit.
    sd = np.maximum(sd, 0.5)
    model = IsolationForest(contamination=CONTAM, random_state=42).fit((arr - mu) / sd)
    base_d_mean = float(np.mean([distance(r) for r in samples]))


def save_model():
    try:
        os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
        joblib.dump({"model": model, "mu": mu, "sd": sd, "base_d_mean": base_d_mean,
                     "features": FEATURES}, MODEL_PATH)
    except Exception as e:  # noqa: BLE001
        print(f"[detector] sauvegarde modèle impossible: {e}", flush=True)


def load_model():
    global model, mu, sd, base_d_mean
    try:
        if os.path.exists(MODEL_PATH):
            d = joblib.load(MODEL_PATH)
            if d.get("features") == FEATURES:
                model, mu, sd, base_d_mean = d["model"], d["mu"], d["sd"], d["base_d_mean"]
                return True
    except Exception as e:  # noqa: BLE001
        print(f"[detector] chargement modèle impossible: {e}", flush=True)
    return False


def loop():
    time.sleep(10)  # laisse Prometheus accumuler un peu d'historique
    if load_model():
        with lock:
            state["trained"] = True
            state["reason"] = "modèle chargé (persisté)"
        TRAINEDG.set(1)
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
                    fit(baseline)
                    save_model()
                    state["trained"] = True
                    state["reason"] = "modèle entraîné"
                    TRAINEDG.set(1)
            else:
                d = distance(feats)
                excess = max(0.0, d - base_d_mean)
                score = min(100.0, excess * 6.0)
                # Flag piloté par la distance standardisée (fiable sur gros écarts).
                # L'Isolation Forest est conservé en corroboration (exposé en info).
                try:
                    if_outlier = int(model.predict(((np.asarray(feats) - mu) / sd).reshape(1, -1))[0]) == -1
                except Exception:
                    if_outlier = False
                is_anom = excess > DIST_FLAG
                state["if_outlier"] = if_outlier
                state["distance"] = round(d, 2)
                state["score"] = round(score, 1)
                state["is_anomaly"] = bool(is_anom)
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


@app.post("/retrain")
def retrain():
    """Force un ré-apprentissage (ex. après un changement de profil de trafic)."""
    with lock:
        state["trained"] = False
        state["reason"] = "ré-apprentissage demandé"
        baseline.clear()
    TRAINEDG.set(0)
    return {"status": "retraining"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
