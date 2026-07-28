"""
Bot de PAPER TRADING Forex - version CLOUD v2 (profil "risque modere +++")
====================================================================================

Concu pour etre declenche automatiquement toutes les 15 minutes par GitHub
Actions. Utilise UNIQUEMENT l'environnement "practice" (demo) d'OANDA.

CHANGEMENTS PAR RAPPORT A LA V1 :
- Capital de reference fixe a 10 000 CHF (au lieu du solde reel du compte
  demo, qui peut etre bien plus eleve) : tout le calcul de risque se base
  sur ce capital notionnel, pour simuler un depart realiste.
- Risque par trade porte a 2% (au lieu de 1%) du capital de reference.
- Diversification sur 3 paires majeures : EUR_USD, GBP_USD, USD_JPY.
- Stop loss 25 pips / Take profit 50 pips (ratio 1:2).
- Garde-fous portefeuille :
    * plafond d'utilisation de marge cumulee (evite le sur-engagement si
      plusieurs paires signalent en meme temps)
    * coupe-circuit de perte journaliere (arrete l'ouverture de nouveaux
      trades pour le reste de la journee si la perte du jour depasse un
      seuil defini)

Ce script reste un outil pedagogique. Aucun gain n'est garanti.
"""

import os
import sys
import json
from datetime import date

import requests

# ------------------------------------------------------------------
# CONFIGURATION - PROFIL "RISQUE MODERE +++"
# ------------------------------------------------------------------

OANDA_API_KEY = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")

# URL FIXE sur l'environnement practice (demo). Ne jamais changer.
OANDA_BASE_URL = "https://api-fxpractice.oanda.com"

NOTIONAL_CAPITAL_CHF = 10000.0   # capital de reference pour le calcul du risque
RISK_PER_TRADE_PCT = 2.0         # % du capital notionnel risque par trade

INSTRUMENTS = ["EUR_USD", "GBP_USD", "USD_JPY"]
GRANULARITY = "M15"
FAST_SMA = 20
SLOW_SMA = 50

STOP_LOSS_PIPS = 25
TAKE_PROFIT_PIPS = 50            # ratio risque/rendement 1:2

MAX_TRADES_PER_DAY_PER_PAIR = 2

ASSUMED_MARGIN_RATE = 1 / 30     # levier suppose 30:1 (standard UE sur les majors)
MAX_MARGIN_USAGE_PCT = 50.0      # jamais plus de 50% du capital notionnel en marge cumulee

DAILY_LOSS_CIRCUIT_BREAKER_PCT = 4.0  # stoppe les nouveaux trades si -4% du capital sur la journee

STATE_FILE = "bot_state.json"


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
    default_state = {
        "date": str(date.today()),
        "start_of_day_nav": None,
        "trades_today": {instr: 0 for instr in INSTRUMENTS},
    }
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") == str(date.today()) and isinstance(state.get("trades_today"), dict):
            for instr in INSTRUMENTS:
                state["trades_today"].setdefault(instr, 0)
            return state
    return default_state


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


def calculate_units(instrument):
    """Taille de position basee sur un risque fixe de RISK_PER_TRADE_PCT
    du capital notionnel, compte tenu de la distance du stop loss."""
    risk_amount = NOTIONAL_CAPITAL_CHF * (RISK_PER_TRADE_PCT / 100)
    stop_distance = STOP_LOSS_PIPS * pip_size(instrument)
    units = risk_amount / stop_distance
    return max(1, int(units))


def estimate_margin(units, price):
    notional = abs(units) * price
    return notional * ASSUMED_MARGIN_RATE


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
    log(f"Ordre envoye : {units} unites de {instrument} pres de {price} "
        f"(SL {sl} / TP {tp})")


def main():
    check_config()
    state = load_state()

    account = get_account_summary()
    nav = float(account["NAV"])
    margin_used = float(account["marginUsed"])

    if state["start_of_day_nav"] is None:
        state["start_of_day_nav"] = nav

    daily_pnl = nav - state["start_of_day_nav"]
    daily_loss_limit = -(DAILY_LOSS_CIRCUIT_BREAKER_PCT / 100) * NOTIONAL_CAPITAL_CHF
    circuit_breaker_tripped = daily_pnl <= daily_loss_limit

    log(f"NAV = {nav:.2f} | Marge utilisee = {margin_used:.2f} | "
        f"PnL du jour = {daily_pnl:.2f} (seuil coupe-circuit {daily_loss_limit:.2f})")

    if circuit_breaker_tripped:
        log("COUPE-CIRCUIT DECLENCHE : perte journaliere >= seuil, "
            "aucun nouveau trade ne sera ouvert aujourd'hui.")

    margin_budget = (MAX_MARGIN_USAGE_PCT / 100) * NOTIONAL_CAPITAL_CHF

    for instrument in INSTRUMENTS:
        try:
            closes = get_candles(instrument, GRANULARITY)
            signal = get_signal(closes)
            position = get_open_position(instrument)
            price = closes[-1]
            trades_today = state["trades_today"].get(instrument, 0)

            log(f"{instrument} = {price} | Signal = {signal} | Position = {position} | "
                f"Trades aujourd'hui = {trades_today}/{MAX_TRADES_PER_DAY_PER_PAIR}")

            if circuit_breaker_tripped:
                continue
            if trades_today >= MAX_TRADES_PER_DAY_PER_PAIR:
                log(f"{instrument} : limite quotidienne atteinte, aucun ordre.")
                continue
            if signal is None:
                continue
            if signal == "buy" and position == "long":
                continue
            if signal == "sell" and position == "short":
                continue

            units = calculate_units(instrument)
            if signal == "sell":
                units = -units

            new_trade_margin = estimate_margin(units, price)
            if margin_used + new_trade_margin > margin_budget:
                log(f"{instrument} : trade ignore, depasserait le plafond de marge "
                    f"({margin_used:.2f} + {new_trade_margin:.2f} > {margin_budget:.2f}).")
                continue

            place_market_order(instrument, units, price)
            state["trades_today"][instrument] = trades_today + 1
            margin_used += new_trade_margin  # reserve la marge pour les paires suivantes de ce cycle

        except requests.exceptions.RequestException as e:
            log(f"{instrument} : erreur reseau/API : {e}")
        except Exception as e:
            log(f"{instrument} : erreur inattendue : {e}")

    save_state(state)


if __name__ == "__main__":
    main()
