"""Générateur de trafic légitime — Resilience-Alpha.

Simule une activité "normale" en continu (lectures fréquentes + petits paiements
occasionnels) pour donner une baseline au modèle ML et une vie au cockpit.
Utilise son propre compte, pour ne pas gêner la démo manuelle (alice).
"""
import os
import time
import random

import requests

API = os.environ.get("API_URL", "http://api:8000")
AUTH = os.environ.get("AUTH_URL", "http://auth:8000")
USER = os.environ.get("TG_USER", "trafficbot")
PASSWORD = os.environ.get("TG_PASSWORD", "trafficbot-pw")
BASE_INTERVAL = float(os.environ.get("TG_INTERVAL", "1.5"))  # secondes (moyenne)


def wait_up():
    for _ in range(60):
        try:
            if requests.get(f"{AUTH}/health", timeout=2).ok and requests.get(f"{API}/health", timeout=2).ok:
                return
        except Exception:
            pass
        time.sleep(2)


def ensure_account():
    # register (ignore si déjà présent), puis login
    try:
        requests.post(f"{AUTH}/register", json={"username": USER, "password": PASSWORD}, timeout=5)
    except Exception:
        pass


def login():
    r = requests.post(f"{AUTH}/login", json={"username": USER, "password": PASSWORD}, timeout=5)
    r.raise_for_status()
    return r.json()["access_token"]


def main():
    print("[traffic-gen] attente des services...", flush=True)
    wait_up()
    ensure_account()
    token = login()
    headers = {"Authorization": f"Bearer {token}"}
    print("[traffic-gen] démarrage du trafic normal", flush=True)

    n = 0
    while True:
        n += 1
        try:
            roll = random.random()
            if roll < 0.55:
                requests.get(f"{API}/accounts/me", headers=headers, timeout=5)
            elif roll < 0.85:
                requests.get(f"{API}/transactions", headers=headers, timeout=5)
            else:
                requests.post(f"{API}/transactions", headers=headers,
                              json={"amount": random.choice([1, 2, 3, 5]),
                                    "recipient": random.choice(["MERCHANT-01", "MERCHANT-02", "SHOP-42"])},
                              timeout=5)
        except Exception as e:  # noqa: BLE001
            print(f"[traffic-gen] erreur: {e}", flush=True)
            try:
                token = login()
                headers = {"Authorization": f"Bearer {token}"}
            except Exception:
                pass
        # intervalle randomisé autour de la moyenne (trafic non régulier)
        time.sleep(max(0.1, random.uniform(0.4, 1.6) * BASE_INTERVAL))


if __name__ == "__main__":
    main()
