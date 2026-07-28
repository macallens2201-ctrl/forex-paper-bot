"""
Bot de PAPER TRADING Forex - version CLOUD (execution unique, pour GitHub Actions)
====================================================================================

Version du bot concue pour etre declenchee automatiquement toutes les 15 minutes
par GitHub Actions, sans rien installer ni faire tourner sur ta machine.

Meme securite que la version locale :
- Utilise UNIQUEMENT l'environnement "practice" (demo) d'OANDA.
- Ne peut pas passer d'ordre en argent reel.
- Strategie : croisement de moyennes mobiles (SMA rapide / SMA lente).

Ce script s'execute une seule fois puis s'arrete (pas de boucle infinie) :
c'est GitHub Actions (via le fichier .github/workflows/forex-bot.yml) qui le
relance automatiquement toutes les 15 minutes, gratuitement.
"""

import os
import sys
import json
from datetime import date

import requests

# ------------------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------------------

OANDA_API_KEY = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")

# URL FIXE sur l'environnement practice (demo). Ne jamais changer.
OANDA_BASE_URL = "https://api-fxpractice.oanda.com"

INSTRUMENT = "EUR_USD"
GRANULARITY = "M15"
FAST_SMA = 20
SLOW_SMA = 50
RISK_PER_TRADE_PCT = 1.0
STOP_LOSS_PIPS = 20
TAKE_PROFIT_PIPS = 40
MAX_TRADES_PER_DAY = 3

STATE_FILE = "bot_state.json"  # garde le compteur de trades du jour entre 2 executions


def log(message):
    print(f"[BOT] {message}")


def check_config():
    if not OANDA_API_KEY or not OANDA_ACCOUNT_ID:
        sys.exit(
            "Secrets manquants : OANDA_API_KEY / OANDA_ACCOUNT_ID. "
            "Verifie les 'Repository secrets' dans les parametres GitHub."
        )
    if "practice" not in OANDA_BASE_URL:
        sys.exit("Securite : ce script doit utiliser l'URL practice uniquement.")


def pip_size(instrument):
    return 0.01 if instrument.endswith("JPY") else 0.0001


def api_headers():
    return {"Authorization": f"Bearer {OANDA_API_KEY}", "Content-Type": "application/json"}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") == str(date.today()):
            return state
    return {"date": str(date.today()), "trades_today": 0}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_candles(instrument, granularity, count=SLOW_SMA + 5):
    url = f"{OANDA_BASE_URL}/v3/instruments/{instrument}/candles"
    params = {"granularity": granularity, "count": count, "price": "M"}
    resp = requests.get(url, headers=api_headers(), params=params, timeout=15)
    resp.raise_for_status()
    candles = resp.json()["candles"]
    return [float(c["mid"]["c"]) for c in candles if c["complete"]]


def get_account_summary():
    url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/summary"
    resp = requests.get(url, headers=api_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["account"]


def get_open_position(instrument):
    url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/positions/{instrument}"
    resp = requests.get(url, headers=api_headers(), timeout=15)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    pos = resp.json()["position"]
    if float(pos["long"]["units"]) != 0:
        return "long"
    if float(pos["short"]["units"]) != 0:
        return "short"
    return None


def calculate_units(balance, instrument):
    risk_amount = balance * (RISK_PER_TRADE_PCT / 100)
    stop_distance = STOP_LOSS_PIPS * pip_size(instrument)
    units = risk_amount / stop_distance
    return max(1, int(units / 100))


def place_market_order(instrument, units, price):
    pip = pip_size(instrument)
    if units > 0:
        sl = round(price - STOP_LOSS_PIPS * pip, 5)
        tp = round(price + TAKE_PROFIT_PIPS * pip, 5)
    else:
        sl = round(price + STOP_LOSS_PIPS * pip, 5)
        tp = round(price - TAKE_PROFIT_PIPS * pip, 5)

    order = {
        "order": {
            "type": "MARKET",
            "instrument": instrument,
            "units": str(units),
            "timeInForce": "FOK",
            "positionFill": "DEFAULT",
            "stopLossOnFill": {"price": f"{sl:.5f}"},
            "takeProfitOnFill": {"price": f"{tp:.5f}"},
        }
    }
    url = f"{OANDA_BASE_URL}/v3/accounts/{OANDA_ACCOUNT_ID}/orders"
    resp = requests.post(url, headers=api_headers(), data=json.dumps(order), timeout=15)
    resp.raise_for_status()
    log(f"Ordre envoye : {units} unites de {instrument} pres de {price}")


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def get_signal(closes):
    fast_now, slow_now = sma(closes, FAST_SMA), sma(closes, SLOW_SMA)
    fast_prev, slow_prev = sma(closes[:-1], FAST_SMA), sma(closes[:-1], SLOW_SMA)
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return None
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "buy"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "sell"
    return None


def main():
    check_config()
    state = load_state()

    closes = get_candles(INSTRUMENT, GRANULARITY)
    signal = get_signal(closes)
    position = get_open_position(INSTRUMENT)
    account = get_account_summary()
    balance = float(account["balance"])
    price = closes[-1]

    log(f"{INSTRUMENT} = {price} | Signal = {signal} | Position = {position} | "
        f"Solde = {balance:.2f} | Trades aujourd'hui = {state['trades_today']}/{MAX_TRADES_PER_DAY}")

    if state["trades_today"] >= MAX_TRADES_PER_DAY:
        log("Limite quotidienne atteinte, aucun ordre.")
    elif signal == "buy" and position != "long":
        place_market_order(INSTRUMENT, calculate_units(balance, INSTRUMENT), price)
        state["trades_today"] += 1
    elif signal == "sell" and position != "short":
        place_market_order(INSTRUMENT, -calculate_units(balance, INSTRUMENT), price)
        state["trades_today"] += 1
    else:
        log("Aucun signal exploitable, rien a faire.")

    save_state(state)


if __name__ == "__main__":
    main()
