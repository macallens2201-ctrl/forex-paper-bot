"""
Bot de PAPER TRADING Forex + matieres premieres - 3 profils de risque
====================================================================================

Ce script pilote UN SEUL bot a la fois, selon la variable d'environnement
RISK_PROFILE ("LOW", "MODERATE" ou "HIGH"). Les 3 profils tournent en
parallele via 3 workflows GitHub Actions distincts (voir .github/workflows/),
chacun pointant vers un compte demo OANDA different.

Utilise UNIQUEMENT l'environnement "practice" (demo) d'OANDA. Ne peut pas
passer d'ordre en argent reel.

Inspiration / references (approches open source existantes) :
- EA31337-Libre (github.com/EA31337/EA31337-Libre) : robot forex open
  source multi-strategies, dont des filtres de tendance sur moyennes
  mobiles longues (utilise ici pour le profil "risque faible").
- ForexSmartBot (github.com/VoxHash/ForexSmartBot) : bot Python open
  source avec gestion du risque avancee ; son risque par defaut de 2%
  par trade est repris ici pour le profil "risque modere".
- Le profil "risque eleve" s'inspire des approches multi-paires /
  multi-strategies a risque plus important de ces memes projets, mais
  SANS martingale ni grille (contrairement a certains EA commerciaux
  type "grid"/"martingale") : chaque trade garde un stop loss fixe et
  independant, pour eviter le risque de ruine associe a ces techniques.

Ce script reste un outil pedagogique. Aucun gain n'est garanti.
"""

import os
import sys
import json
from datetime import date

import requests

# ------------------------------------------------------------------
# PROFILS DE RISQUE
# ------------------------------------------------------------------
# Chaque instrument (forex ou matiere premiere) a desormais ses PROPRES
# parametres SMA / stop / take, car le backtest (2026-07-28, ~69 jours de
# donnees reelles OANDA en M5) montre qu'un seul reglage partage par profil
# ne fonctionne pas bien d'un instrument a l'autre (ex: le couple SMA
# optimal pour l'EUR/USD est carrement perdant sur le cuivre).

PROFILES = {
    "LOW": {
        "label": "Risque Faible",
        "notional_capital": 10000.0,
        "risk_per_trade_pct": 0.5,
        "instruments": {
            "EUR_USD": {"fast_sma": 50, "slow_sma": 80, "sl_pips": 30, "tp_pips": 90},
            "XCU_USD": {"fast_sma": 200, "slow_sma": 300, "sl_pips": 782, "tp_pips": 2346},
        },
        "max_trades_per_day_per_pair": 1,
        "max_margin_usage_pct": 25.0,
        "daily_loss_circuit_breaker_pct": 2.0,
    },
    "MODERATE": {
        "label": "Risque Modere",
        "notional_capital": 10000.0,
        "risk_per_trade_pct": 2.0,
        "instruments": {
            "EUR_USD": {"fast_sma": 20, "slow_sma": 60, "sl_pips": 25, "tp_pips": 50},
            "GBP_USD": {"fast_sma": 20, "slow_sma": 60, "sl_pips": 25, "tp_pips": 50},
            "USD_JPY": {"fast_sma": 20, "slow_sma": 60, "sl_pips": 25, "tp_pips": 50},
            "XCU_USD": {"fast_sma": 30, "slow_sma": 60, "sl_pips": 651, "tp_pips": 1302},
            "NATGAS_USD": {"fast_sma": 20, "slow_sma": 30, "sl_pips": 4, "tp_pips": 8},
        },
        "max_trades_per_day_per_pair": 2,
        "max_margin_usage_pct": 50.0,
        "daily_loss_circuit_breaker_pct": 4.0,
    },
    "HIGH": {
        "label": "Risque Eleve",
        "notional_capital": 10000.0,
        "risk_per_trade_pct": 5.0,
        "instruments": {
            "EUR_USD": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "GBP_USD": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "USD_JPY": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "GBP_JPY": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "AUD_USD": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "EUR_JPY": {"fast_sma": 8, "slow_sma": 15, "sl_pips": 15, "tp_pips": 30},
            "XCU_USD": {"fast_sma": 20, "slow_sma": 45, "sl_pips": 391, "tp_pips": 782},
            "NATGAS_USD": {"fast_sma": 10, "slow_sma": 15, "sl_pips": 2, "tp_pips": 4},
        },
        "max_trades_per_day_per_pair": 3,
        "max_margin_usage_pct": 75.0,
        "daily_loss_circuit_breaker_pct": 8.0,
    },
}
# Historique des recalibrages :
#
# 2026-07-28 (a) SMA forex M15 -> plateau robuste retenu pour MODERATE/HIGH,
# LOW laisse inchange (signal trop faible, pic isole non robuste).
#
# 2026-07-28 (b) Passage a la granularite M5 + execution toutes les 5 min
# (au lieu de M15/15 min), rendu possible par le passage du repo GitHub en
# public (minutes Actions illimitees). Backtest sur ~69 jours de donnees
# reelles M5 : gain confirme sur les 3 profils par rapport au M15 (LOW :
# 2/66 combinaisons gagnantes -> 13/36 avec de meilleures performances ;
# MODERATE : +/-neutre -> plateau robuste tres positif ; HIGH : deja bon,
# encore ameliore). Nouveaux reglages : LOW 50/80, MODERATE 20/60,
# HIGH 8/15 (periodes en nombre de bougies M5).
#
# 2026-07-28 (c) Ajout de matieres premieres apres backtest comparatif sur
# Or, Argent, Petrole WTI, Brent, Gaz naturel et Cuivre (meme fenetre de
# 69 jours, SL/TP recalibres par instrument pour une distance de stop
# proportionnellement equivalente a celle utilisee sur l'EUR/USD, mesuree
# en multiples de l'amplitude moyenne par bougie M5). Resultats : Or et
# Petrole (WTI/Brent) rejetes (quasi aucune combinaison gagnante, marche
# trop directionnel/tendanciel pour un croisement de moyennes sur cette
# periode). Cuivre et Gaz naturel retenus (plateaux robustes et positifs
# sur les 3 profils). Argent teste mais moins robuste que le cuivre a risque
# egal, non retenu. Le cuivre est ajoute a LOW (seul le plus selectif est
# garde, en coherence avec sa philosophie 1 seul instrument tres selectif),
# le cuivre ET le gaz naturel sont ajoutes a MODERATE et HIGH.
#
# Attention : le gaz naturel a une frequence de signal tres elevee en brut
# (jusqu'a plusieurs dizaines par jour) ; le plafond "max_trades_per_day_per_pair"
# du profil filtre fortement ce nombre en production, donc le nombre reel de
# trades sera nettement inferieur a celui observe dans le backtest brut.
# Ses stops/takes en "pips" paraissent tres petits (2-8) : c'est normal, le
# gaz naturel cote avec une precision differente du forex (voir pip_size) ;
# en proportion du prix, ces stops sont calibres pour etre comparables a
# ceux utilises sur l'EUR/USD.
#
# A revalider periodiquement (walk-forward) : un backtest sur 69 jours reste
# un seul regime de marche, pas une garantie de performance future.

GRANULARITY = "M5"
ASSUMED_MARGIN_RATE = 1 / 30   # levier suppose 30:1 (standard UE sur les majors forex)

# Taille de pip et taux de marge specifiques a certains instruments non-forex.
PIP_SIZES = {
    "XAU_USD": 0.01,
    "XAG_USD": 0.0001,
    "XCU_USD": 0.0001,
    "NATGAS_USD": 0.01,
}
MARGIN_RATES = {
    "XCU_USD": 0.10,
    "NATGAS_USD": 0.10,
}

OANDA_API_KEY = os.environ.get("OANDA_API_KEY", "")
OANDA_ACCOUNT_ID = os.environ.get("OANDA_ACCOUNT_ID", "")
OANDA_BASE_URL = "https://api-fxpractice.oanda.com"  # URL FIXE practice/demo uniquement

RISK_PROFILE = os.environ.get("RISK_PROFILE", "").upper()


def log(message):
    print(f"[BOT-{RISK_PROFILE}] {message}")


def check_config():
    if RISK_PROFILE not in PROFILES:
        sys.exit(f"RISK_PROFILE invalide : '{RISK_PROFILE}'. Valeurs possibles : {list(PROFILES)}")
    if not OANDA_API_KEY or not OANDA_ACCOUNT_ID:
        sys.exit(
            "Secrets manquants : OANDA_API_KEY / OANDA_ACCOUNT_ID. "
            "Verifie les 'Repository secrets' dans les parametres GitHub."
        )
    if "practice" not in OANDA_BASE_URL:
        sys.exit("Securite : ce script doit utiliser l'URL practice uniquement.")


def pip_size(instrument):
    if instrument in PIP_SIZES:
        return PIP_SIZES[instrument]
    return 0.01 if instrument.endswith("JPY") else 0.0001


def margin_rate(instrument):
    return MARGIN_RATES.get(instrument, ASSUMED_MARGIN_RATE)


def api_headers():
    return {"Authorization": f"Bearer {OANDA_API_KEY}", "Content-Type": "application/json"}


def state_file_path(cfg):
    return f"bot_state_{RISK_PROFILE.lower()}.json"


def load_state(cfg):
    path = state_file_path(cfg)
    default_state = {
        "date": str(date.today()),
        "start_of_day_nav": None,
        "trades_today": {instr: 0 for instr in cfg["instruments"]},
    }
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if state.get("date") == str(date.today()) and isinstance(state.get("trades_today"), dict):
            for instr in cfg["instruments"]:
                state["trades_today"].setdefault(instr, 0)
            return state
    return default_state


def save_state(cfg, state):
    with open(state_file_path(cfg), "w", encoding="utf-8") as f:
        json.dump(state, f)


def get_candles(instrument, count):
    url = f"{OANDA_BASE_URL}/v3/instruments/{instrument}/candles"
    params = {"granularity": GRANULARITY, "count": count, "price": "M"}
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


def calculate_units(cfg, instrument, instr_cfg):
    risk_amount = cfg["notional_capital"] * (cfg["risk_per_trade_pct"] / 100)
    stop_distance = instr_cfg["sl_pips"] * pip_size(instrument)
    units = risk_amount / stop_distance
    return max(1, int(units))


def estimate_margin(units, price, instrument):
    return abs(units) * price * margin_rate(instrument)


def sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def get_signal(closes, fast_period, slow_period):
    fast_now, slow_now = sma(closes, fast_period), sma(closes, slow_period)
    fast_prev, slow_prev = sma(closes[:-1], fast_period), sma(closes[:-1], slow_period)
    if None in (fast_now, slow_now, fast_prev, slow_prev):
        return None
    if fast_prev <= slow_prev and fast_now > slow_now:
        return "buy"
    if fast_prev >= slow_prev and fast_now < slow_now:
        return "sell"
    return None


def place_market_order(cfg, instrument, units, price, instr_cfg):
    pip = pip_size(instrument)
    sl_pips = instr_cfg["sl_pips"]
    tp_pips = instr_cfg["tp_pips"]
    if units > 0:
        sl = round(price - sl_pips * pip, 5)
        tp = round(price + tp_pips * pip, 5)
    else:
        sl = round(price + sl_pips * pip, 5)
        tp = round(price - tp_pips * pip, 5)

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
    log(f"Ordre envoye : {units} unites de {instrument} pres de {price} (SL {sl} / TP {tp})")


def main():
    check_config()
    cfg = PROFILES[RISK_PROFILE]
    log(f"Profil : {cfg['label']} | Instruments : {list(cfg['instruments'])} | "
        f"Risque/trade : {cfg['risk_per_trade_pct']}% | Granularite : {GRANULARITY}")

    state = load_state(cfg)

    account = get_account_summary()
    nav = float(account["NAV"])
    margin_used = float(account["marginUsed"])

    if state["start_of_day_nav"] is None:
        state["start_of_day_nav"] = nav

    daily_pnl = nav - state["start_of_day_nav"]
    daily_loss_limit = -(cfg["daily_loss_circuit_breaker_pct"] / 100) * cfg["notional_capital"]
    circuit_breaker_tripped = daily_pnl <= daily_loss_limit

    log(f"NAV = {nav:.2f} | Marge utilisee = {margin_used:.2f} | "
        f"PnL du jour = {daily_pnl:.2f} (seuil coupe-circuit {daily_loss_limit:.2f})")

    if circuit_breaker_tripped:
        log("COUPE-CIRCUIT DECLENCHE : perte journaliere >= seuil, aucun nouveau trade aujourd'hui.")

    margin_budget = (cfg["max_margin_usage_pct"] / 100) * cfg["notional_capital"]

    for instrument, instr_cfg in cfg["instruments"].items():
        try:
            closes = get_candles(instrument, instr_cfg["slow_sma"] + 5)
            signal = get_signal(closes, instr_cfg["fast_sma"], instr_cfg["slow_sma"])
            position = get_open_position(instrument)
            price = closes[-1]
            trades_today = state["trades_today"].get(instrument, 0)

            log(f"{instrument} = {price} | Signal = {signal} | Position = {position} | "
                f"Trades aujourd'hui = {trades_today}/{cfg['max_trades_per_day_per_pair']}")

            if circuit_breaker_tripped:
                continue
            if trades_today >= cfg["max_trades_per_day_per_pair"]:
                continue
            if signal is None:
                continue
            if signal == "buy" and position == "long":
                continue
            if signal == "sell" and position == "short":
                continue

            units = calculate_units(cfg, instrument, instr_cfg)
            if signal == "sell":
                units = -units

            new_trade_margin = estimate_margin(units, price, instrument)
            if margin_used + new_trade_margin > margin_budget:
                log(f"{instrument} : trade ignore, depasserait le plafond de marge.")
                continue

            place_market_order(cfg, instrument, units, price, instr_cfg)
            state["trades_today"][instrument] = trades_today + 1
            margin_used += new_trade_margin

        except requests.exceptions.RequestException as e:
            log(f"{instrument} : erreur reseau/API : {e}")
        except Exception as e:
            log(f"{instrument} : erreur inattendue : {e}")

    save_state(cfg, state)


if __name__ == "__main__":
    main()
