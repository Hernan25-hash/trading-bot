from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL
import pandas as pd
import numpy as np
import time
import datetime
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
import time

last_request = 0
MIN_DELAY = 0.2  # 5 requests per second max

def rate_limit():
    global last_request
    now = time.time()
    if now - last_request < MIN_DELAY:
        time.sleep(MIN_DELAY - (now - last_request))
    last_request = time.time()
import os, sys, atexit
import logging

klines_cache = {}
cache_time = {}
CACHE_TTL = 30  # seconds
def get_klines(symbol, interval, limit=50):
    rate_limit()
    key = f"{symbol}_{interval}"
    now = time.time()

    if key in klines_cache and (now - cache_time[key]) < CACHE_TTL:
        return klines_cache[key]

    # 🔥 DITO DAPAT DIRECT BINANCE CALL
    data = client.futures_klines(
        symbol=symbol,
        interval=interval,
        limit=limit
    )

    klines_cache[key] = data
    cache_time[key] = now

    return data



from dotenv import load_dotenv
load_dotenv()
# =====================
# CONFIG / SETTINGS
# =====================

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAME = "5m"
# 🔥 ADD THIS HERE
weights = {
    "1m": 1,
    "5m": 1,
    "15m": 2,
    "1h": 3,
    "4h": 4,
    "1d": 5
}

MAX_TRADES_PER_CYCLE = 1
MIN_BALANCE = 10
daily_loss_limit = -20



lock_file = os.path.join(os.getcwd(), "bot.lock")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(message)s"
)

def log_step(step, msg):
    logging.info(f"[{step}] {msg}")
def cleanup():
    try:
        if os.path.exists(lock_file):
            os.remove(lock_file)
    except:
        pass

atexit.register(cleanup)

# Prevent multiple runs
if os.path.exists(lock_file):
    print("Bot already running!")
    sys.exit()

# Create lock file
with open(lock_file, "w") as f:
    f.write(str(os.getpid()))
# =====================
# DAILY LOSS PROTECTION
# =====================
daily_pnl = 0
daily_loss_limit = -20   # max allowed loss per day (USDT)
# =====================
# SMART LEVERAGE ENGINE
# =====================
def smart_leverage(atr, price, balance):
    volatility = atr / price

    max_lev = 8
    min_lev = 1

    # =====================
    # BASE LEVERAGE (market volatility first)
    # =====================
    if volatility > 0.015:
        lev = 1
    elif volatility > 0.01:
        lev = 2
    elif volatility > 0.006:
        lev = 3
    elif volatility > 0.003:
        lev = 5
    else:
        lev = 7

    # =====================
    # SCALABLE BALANCE FACTOR (IMPORTANT PART)
    # =====================
    # log scaling so it works from 100 → 1,000,000+
    import math

    balance_factor = math.log10(max(balance, 10))  # prevents log(0)

    # normalize to 0–1 range roughly
    # 100 = 2, 1,000 = 3, 10,000 = 4, 100,000 = 5, 1,000,000 = 6
    normalized = (balance_factor - 2) / 4
    normalized = max(0, min(normalized, 1))

    # leverage adjustment curve (smooth, not abrupt)
    lev = lev + (normalized * 2.5)

    # =====================
    # EXTREME VOLATILITY OVERRIDE
    # =====================
    if volatility > 0.012:
        lev = min(2, lev)

    if volatility < 0.002:
        lev = min(8, lev)

    # =====================
    # FINAL LIMITS
    # =====================
    return max(min_lev, min(int(lev), max_lev))

# =====================
# API
# =====================

api_key = os.getenv("API_KEY")
api_secret = os.getenv("API_SECRET")

client = Client(api_key, api_secret)


# =====================
# SETTINGS
# =====================

TIMEFRAME = "5m"
RISK_PER_TRADE = 0.01

TRADE_ENABLED = True   # 🔴 SAFE MODE (set True kapag ready ka na)

MIN_BALANCE = 10 


log_step("START", "SMART SNIPER BOT STARTED")
# =====================
# COOLDOWN TRACKER (WIN/LOSS PROTECTION)
# =====================
trade_lock = {}
# =====================
# COOLDOWN SYSTEM (prevent overtrading on same symbol)
# =====================
import datetime

last_trade_time = {}
COOLDOWN_MINUTES = 10
def can_trade(symbol):
    if symbol not in last_trade_time:
        return True

    diff = (datetime.datetime.now() - last_trade_time[symbol]).seconds / 60
    return diff >= 10
# =====================
# SMART TIMEFRAME DETECTOR (based on recent volatility)
# =====================
def detect_timeframe(symbol):

    df_5m = get_klines(symbol=symbol, interval="5m", limit=50)
    df_15m = get_klines(symbol=symbol, interval="15m", limit=50)
    df_1h = get_klines(symbol=symbol, interval="1h", limit=50)
    df_4h = get_klines(symbol=symbol, interval="4h", limit=50)
    df_1d = get_klines(symbol=symbol, interval="1d", limit=50)

    def get_vol(df):
        closes = [float(x[4]) for x in df]
        return np.std(closes) / np.mean(closes)

    vol_5m = get_vol(df_5m)
    vol_15m = get_vol(df_15m)
    vol_1h = get_vol(df_1h)
    vol_4h = get_vol(df_4h)
    vol_1d = get_vol(df_1d)

    # =====================
    # MARKET REGIME LOGIC
    # =====================

    # 🔥 HIGH VOLATILITY → scalping mode
    if vol_5m > 0.012 or vol_15m > 0.008:
        return "5m"

    # 📊 NORMAL MARKET → intraday
    elif vol_1h > 0.007:
        return "15m"

    # 📈 TRENDING MARKET → swing
    elif vol_4h > 0.006:
        return "1h"

    # 🌊 BIG TREND MODE
    elif vol_1d > 0.005:
        return "4h"

    # 🧠 SLOW / MACRO TREND
    else:
        return "1d"
def check_daily_loss():
    global daily_pnl

    if daily_pnl <= daily_loss_limit:
        print("🛑 DAILY LOSS LIMIT HIT. BOT STOPPED.")
        return False

    return True

def market_regime(price, ema, atr):

    trend = abs(price - ema) / ema
    vol = atr / price

    # STRONG TREND
    if trend > 0.004:
        return "TRENDING"

    # DEAD / SIDEWAYS MARKET
    elif vol < 0.001:
        return "CHOP"

    # NORMAL MARKET
    else:
        return "NEUTRAL"

# =====================
# DATA
# =====================
def get_data(symbol):
    klines = get_klines(symbol=symbol, interval=TIMEFRAME, limit=120)

    df = pd.DataFrame(klines, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","trades","tbb","tbq","ignore"
    ])

    for col in ["open","high","low","close","volume"]:
        df[col] = df[col].astype(float)

    return df


def get_step_size(symbol):
    info = client.futures_exchange_info()

    for s in info["symbols"]:
        if s["symbol"] == symbol:
            for f in s["filters"]:
                if f["filterType"] == "LOT_SIZE":
                    return float(f["stepSize"])

    return 0.001

def multi_tf_confirmation(symbol, direction):
    tfs = ["15m", "1h", "4h", "1d"]

    confirm_score = 0

    for tf in tfs:
        df = get_klines(symbol=symbol, interval=tf, limit=50)

        df = pd.DataFrame(df, columns=[
            "time","open","high","low","close","volume",
            "ct","qav","trades","tbb","tbq","ignore"
        ])

        df["close"] = df["close"].astype(float)

        ema = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]
        price = df["close"].iloc[-1]

        if direction == "BUY" and price > ema:
            confirm_score += 1
        elif direction == "SELL" and price < ema:
            confirm_score += 1
        else:
            confirm_score -= 1

    return confirm_score
def adjust_quantity(qty, step):
    if qty <= 0:
        return 0

    qty = qty - (qty % step)

    if qty < step:
        return 0

    return round(qty, 8)

# =====================
# INDICATORS
# =====================
def analyze(df):
    close = df["close"]

    ema = EMAIndicator(close, window=20).ema_indicator()
    rsi = RSIIndicator(close).rsi()
    atr = AverageTrueRange(df["high"], df["low"], close, window=14).average_true_range()

    price = float(close.iloc[-1])
    ema_val = float(ema.iloc[-1])
    rsi_val = float(rsi.iloc[-1])
    atr_val = float(atr.iloc[-1])

    # EXTRA: volatility ratio (VERY IMPORTANT for smart leverage)
    volatility = atr_val / price

    return {
        "price": price,
        "ema": ema_val,
        "rsi": rsi_val,
        "atr": atr_val,
        "volatility": volatility
    }

def volume_bias(symbol, direction):
    tfs = ["1m", "5m", "15m", "1h", "4h", "1d"]

    buy = 0
    sell = 0

    for tf in tfs:
        df = get_klines(symbol=symbol, interval=tf, limit=50)

        df = pd.DataFrame(df, columns=[
            "time","open","high","low","close","volume",
            "ct","qav","trades","tbb","tbq","ignore"
        ])

        df["close"] = df["close"].astype(float)
        df["volume"] = df["volume"].astype(float)

        price = df["close"].iloc[-1]
        ema = EMAIndicator(df["close"], window=20).ema_indicator().iloc[-1]

        vol_ratio = df["volume"].iloc[-1] / df["volume"].mean()

        if price > ema:
            buy += vol_ratio
        else:
            sell += vol_ratio

    if direction == "BUY":
        return buy - sell
    else:
        return sell - buy

def signal(df, symbol):
    data = analyze(df)

    price = data["price"]
    ema = data["ema"]
    rsi = data["rsi"]
    atr = data["atr"]

    # 🧠 REGIME FILTER (UNCHANGED)
    regime = market_regime(price, ema, atr)

    regime_bonus = 0
    if regime == "CHOP":
        regime_bonus -= 5
    elif regime == "TRENDING":
        regime_bonus += 4
    elif regime == "NEUTRAL":
        regime_bonus += 1

    score = 0

    # 📊 TREND DIRECTION (UNCHANGED LOGIC)
    if price > ema:
        direction = "BUY"
        score += 2
    else:
        direction = "SELL"
        score += 2

    # 🔥 FIX ONLY: volume_bias AFTER direction is set
    volume_pressure = volume_bias(symbol, direction)

    # =====================
    # TREND STRENGTH
    # =====================
    trend_strength = abs(price - ema) / ema

    if trend_strength < 0.0015:
        score -= 1
    elif trend_strength > 0.003:
        score += 2
    elif trend_strength > 0.006:
        score += 3

    # =====================
    # RSI FILTER
    # =====================
    if direction == "BUY" and rsi < 50:
        score += 3
    elif direction == "SELL" and rsi > 50:
        score += 3

    # =====================
    # VOLUME FILTER
    # =====================
    vol = df["volume"].iloc[-1]
    vol_ratio = vol / df["volume"].mean()

    if vol_ratio > 1.5:
        score += 2
    elif vol_ratio > 1.2:
        score += 1
    elif vol_ratio < 0.7:
        score -= 1

    # =====================
    # ATR FILTER
    # =====================
    if (atr / price) > 0.0008:
        score += 1

    # =====================
    # VOLATILITY FILTER
    # =====================
    if vol_ratio > 0.01:
        score -= 2
    elif vol_ratio < 0.003:
        score += 1

    # =====================
    # CHOP SAFETY
    # =====================
    chop = abs(price - ema) / ema
    if chop < 0.002:
        score -= 1
    elif chop > 0.01:
        score += 1

    # =====================
    # REGIME BOOST
    # =====================
    score += regime_bonus

    # =====================
    # VOLUME PRESSURE BOOST
    # =====================
    if volume_pressure > 5:
        score += 3
    elif volume_pressure > 2:
        score += 2
    elif volume_pressure > 0:
        score += 1
    elif volume_pressure < -3:
        score -= 2
    # 🔥 BOOST FINAL SCORE
    score = score * 1.5
    return {
        "score": score,
        "direction": direction,
        "price": price,
        "atr": atr
    }
# =====================
# BALANCE
# =====================
def get_balance():
    balances = client.futures_account_balance()
    for b in balances:
        if b["asset"] == "USDT":
            return float(b["availableBalance"])
    return 0.0
def can_afford_trade(size, price, leverage):
    available = get_balance()
    required_margin = (size * price) / leverage

    # safety buffer 70%
    return required_margin <= available * 0.98
# =====================
# RISK GUARD (anti-high volatility filter)
# =====================
def risk_guard(atr, price):
    return (atr / price) < 0.02

# =====================
# POSITION SIZE (risk-based)
# =====================
# =====================
# SMART POSITION SIZE
# =====================
def position_size(balance, price, leverage, total_score, volatility):

    # =====================
    # SAFETY CHECK
    # =====================
    if balance <= 0 or price <= 0:
        return 0

    # =====================
    # SIGNAL QUALITY BASE
    # =====================
    if total_score < 3:
        allocation = 0.10

    elif total_score < 5:
        allocation = 0.25

    elif total_score < 8:
        allocation = 0.50

    # =====================
    # SNIPER MODE (NEAR ALL-IN)
    # =====================
    elif total_score < 10:
        allocation = 0.75
    else:
        allocation = 0.90   # 🔥 near all-in (safe version)

    # =====================
    # VOLATILITY PROTECTION
    # =====================
    if volatility > 0.015:
        allocation *= 0.30   # extreme risk cut

    elif volatility > 0.010:
        allocation *= 0.50

    elif volatility > 0.007:
        allocation *= 0.75

    # =====================
    # FINAL SAFETY CAP (IMPORTANT)
    # =====================
    allocation = min(allocation, 0.90)

    usable_balance = balance * allocation
    notional = usable_balance * leverage
    size = notional / price

    # HARD CAP (anti wipe protection)
    max_notional = balance * leverage * 0.8
    size = min(size, max_notional / price)

    return size

# =====================
# EXECUTION (with SL/TP logic prepared)
# =====================
def place_trade(symbol, direction, size, price, atr):

    try:
        # =====================
        # CANCEL EXISTING ORDERS
        # =====================
        try:
            client.futures_cancel_all_open_orders(symbol=symbol)
        except:
            pass

        side = SIDE_BUY if direction == "BUY" else SIDE_SELL

        # =====================
        # SMART TP/SL ENGINE
        # =====================
        volatility = atr / price

        # Binance futures fee estimate (ITO HINDI NAWALA)
        fee_buffer = price * 0.0015

        # Dynamic ATR multipliers
        if volatility > 0.01:
            sl_mult = 3.0
            tp_mult = 5.0
        elif volatility > 0.005:
            sl_mult = 2.5
            tp_mult = 4.0
        else:
            sl_mult = 1.8
            tp_mult = 3.0

        # BUY / SELL logic
        if direction == "BUY":
            sl_price = price - (atr * sl_mult) - fee_buffer
            tp_price = price + (atr * tp_mult) + fee_buffer
        else:
            sl_price = price + (atr * sl_mult) + fee_buffer
            tp_price = price - (atr * tp_mult) - fee_buffer

        # =====================
        # MIN NOTIONAL CHECK
        # =====================
        min_notional = 5  # Binance Futures safety

        if size * price < min_notional:
            print(f"❌ BELOW MIN NOTIONAL: {size * price:.2f} USDT - SKIP TRADE")
            return None

        # =====================
        # MARKET ENTRY
        # =====================
        order = client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            quantity=size
        )

        order_id = order["orderId"]

        time.sleep(0.3)

        filled_order = client.futures_get_order(
            symbol=symbol,
            orderId=order_id
        )

        entry_price = float(filled_order.get("avgPrice") or price)

        # =====================
        # PRICE PRECISION (FIXED PLACE)
        # =====================
        price_precision = len(str(price).split(".")[1]) if "." in str(price) else 2

        print(f"\n🚀 TRADE EXECUTED {symbol} {direction}")
        print("Entry:", entry_price)
        print("SL:", sl_price)
        print("TP:", tp_price)

        # =====================
        # STOP LOSS
        # =====================
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if direction == "BUY" else SIDE_BUY,
            type="STOP_MARKET",
            stopPrice=round(sl_price, price_precision),
            closePosition=True,
            workingType="MARK_PRICE"
        )

        # =====================
        # TAKE PROFIT
        # =====================
        client.futures_create_order(
            symbol=symbol,
            side=SIDE_SELL if direction == "BUY" else SIDE_BUY,
            type="TAKE_PROFIT_MARKET",
            stopPrice=round(tp_price, price_precision),
            closePosition=True,
            workingType="MARK_PRICE"
        )

        return order

    except Exception as e:
        print("ORDER ERROR:", e)
        return None
        # =====================
# POSITION CHECKER
# =====================
def has_open_position(symbol):

    try:
        positions = client.futures_position_information(symbol=symbol)

        for p in positions:

            amt = float(p["positionAmt"])

            if amt != 0:
                return True

        return False

    except Exception as e:
        print("Position check error:", e)
        return False
def preload_data(symbol):
    tfs = ["1m","5m","15m","1h","4h","1d"]
    for tf in tfs:
        get_klines(symbol, tf, 120)
    

# =====================
# MAIN LOOP (SNIPER MODE)
# =====================

best = None
while True:
    if daily_pnl <= daily_loss_limit:
        print("STOP BOT - DAILY LOSS HIT")
        break
    log_step("CYCLE", "Starting new scan cycle")

    # 🔥 ADD THIS HERE (IMPORTANT)
    for symbol in SYMBOLS:
        preload_data(symbol)
        time.sleep(0.1)
    trades_this_cycle = 0
    best_symbol = None
    best_signal = None
    best_score = -999

    for symbol in SYMBOLS:
        log_step("SCAN", f"Checking {symbol}")

        trend_tfs = ["1m", "5m", "15m", "1h", "4h", "1d"]

        buy_score = 0
        sell_score = 0

        for tf in trend_tfs:

            trend_df = get_klines(symbol, tf, 120)

            trend_df = pd.DataFrame(trend_df, columns=[
                "time","open","high","low","close","volume",
                "ct","qav","trades","tbb","tbq","ignore"
            ])

            trend_df["close"] = trend_df["close"].astype(float)

            ema = EMAIndicator(trend_df["close"], window=20).ema_indicator().iloc[-1]
            price = trend_df["close"].iloc[-1]

            # ✅ FIX: scoring MUST be inside loop
            if price > ema:
                buy_score += weights[tf] * (1 / len(trend_tfs))
            else:
                sell_score += weights[tf] * (1 / len(trend_tfs))
                print(tf, "=>", "BUY" if price > ema else "SELL", price, ema)

        trend_direction = "BUY" if buy_score > sell_score else "SELL"
        

        score = min(abs(buy_score - sell_score), 10)

        log_step(
        "TREND",
        f"{symbol} trend={trend_direction} buy={buy_score:.2f} sell={sell_score:.2f} score={score:.2f}"
    )

        # volatility (optional enhancement)
        vol = trend_df["close"].pct_change().std()
        final_score = score + vol

        log_step("SCORE", f"{symbol} buy={buy_score:.2f} sell={sell_score:.2f} final={final_score:.2f}")

        candidate = {
        "symbol": symbol,
        "score": final_score,
        "direction": trend_direction,
        "total_score": final_score
    }

        if final_score > best_score:
            best_score = final_score
            best_symbol = symbol
            best_signal = candidate

        # AFTER LOOP = BEST TRADE
        if best and best["total_score"] >= 2:

            symbol = best_signal["symbol"]

            tf = detect_timeframe(symbol)
        print(symbol, "selected TF:", tf)

        df = get_klines(symbol, tf, 120)

    # =====================
    # SMART TIMEFRAME PICK
        # =====================
        tf = detect_timeframe(best_signal["symbol"])
        print(best_signal["symbol"], "selected TF:", tf)

        df = get_klines(best_signal["symbol"], tf, 120)

        df = pd.DataFrame(df, columns=[
        "time","open","high","low","close","volume",
        "ct","qav","trades","tbb","tbq","ignore"
        ])

        for col in ["open","high","low","close","volume"]:
            df[col] = df[col].astype(float)

        # =====================
        # ANALYZE + FILTER
        # =====================

        data = analyze(df)

        trend_strength = abs(data["ema"] - data["price"]) / data["price"]
        volatility = data["atr"] / data["price"]

        # 1️⃣ FIRST SIGNAL CALL (ONLY ONCE)
        sig = signal(df, best_signal["symbol"])
        log_step(
            "SIGNAL",
            f"{best_signal['symbol']} direction={sig['direction']} score={sig['score']:.2f}"
)

        if not sig or sig["direction"] is None:
            log_step("SKIP", f"{best_signal['symbol']} invalid signal")
            continue

        # 2️⃣ CONFIDENCE CHECK
        confidence = abs(buy_score - sell_score) / sum(weights.values())

        if sig["direction"] != trend_direction and confidence < 0.25:
            log_step("SKIP", f"{best_signal['symbol']} weak trend + mismatch")
            continue

        # 3️⃣ MARKET FILTERS
        if volatility > 0.015:
            log_step("SKIP", f"{best_signal['symbol']} cooldown active")
            continue

        if volatility < 0.0003:
            log_step("SKIP", f"{best_signal['symbol']} low volatility")
            continue

        if data["rsi"] > 80 or data["rsi"] < 20:
            log_step("SKIP", f"{best_signal['symbol']} RSI out of bounds")
            continue

        if trend_strength < 0.0008:
            log_step("SKIP", f"{best_signal['symbol']} weak trend")
            continue

        # 4️⃣ REGIME FILTER
        regime = market_regime(data["price"], data["ema"], data["atr"])
        log_step("REGIME", f"{best_signal['symbol']} regime={regime}")
        

        if regime == "CHOP":
            log_step("SKIP", f"{best_signal['symbol']} CHOP MARKET")
            continue

        # 5️⃣ SCORE CHECK
        log_step("SCORE", f"{best_signal['symbol']} score: {sig['score']}")

        if sig["score"] < 1:
            log_step("SKIP", f"{best_signal['symbol']} low score")
            continue

        # 6️⃣ VOLATILITY CHECK (extra safety)
        sig_volatility = sig["atr"] / sig["price"]

        if sig_volatility > 0.02:
            log_step("SKIP", f"{best_signal['symbol']} insufficient balance")
            continue

        if sig_volatility < 0.0005:
            log_step("SKIP", f"{best_signal['symbol']} low volatility")
            continue

        trend = trend_strength

        if trend < 0.001:
            log_step("SKIP", f"{best_signal['symbol']} weak trend")
            continue
        # =====================
        # SCORING CONFIRMATION
        # =====================
        tf_confirm = multi_tf_confirmation(best_signal["symbol"], sig["direction"])
        total_score = sig["score"] + tf_confirm
        log_step("CHECK", f"{best_signal['symbol']} PASS CHECK: {sig['score']}, {total_score}")
        # 🔥 DEBUG HERE (IMPORTANT)
        print("DEBUG SCORE:", sig["score"])
        print("DEBUG TOTAL:", total_score)
        print("DEBUG DIRECTION:", sig["direction"])
        print("DEBUG TREND:", trend_direction)

        print(best_signal["symbol"], "TOTAL SCORE:", total_score)
        

        if total_score < 1.5:
            print("SKIP LOW TOTAL")
            log_step("SKIP", f"{best_signal['symbol']} low total score")
            continue

        print(
            best_signal["symbol"],
            "base score:", sig["score"],
            "TF confirm:", tf_confirm,
            "TOTAL:", total_score
)

        # =====================
        # BEST SIGNAL TRACKING
        # =====================
        if total_score > best_score:
            best_score = total_score

            best = {
            "symbol": best_signal["symbol"],
            **sig,
            "tf": tf,
            "tf_confirm": tf_confirm,
            "volatility": volatility,
            "total_score": total_score
    }

        print("\n🔥 NEW BEST SNIPER SIGNAL:", best)

    # =====================
    # DEBUG FINAL CHECK (ILAGAY DITO)
    # =====================
    if not best:
        print("DEBUG FINAL CHECK:")
        print("best:", best)
        print("total_score:", best.get("total_score"))
    
        print("No valid best setup")
        time.sleep(60)
        continue

    # TRADE CHECK
    if best and best["total_score"] >= 2:

        symbol = best["symbol"]

        tf = detect_timeframe(symbol)
        print(symbol, "selected TF:", tf)

        df = get_data(symbol)  # or get_klines(symbol, tf)

        # =====================
        # COOLDOWN CHECK (FIXED)
        # =====================
        if symbol in trade_lock:
            cooldown = time.time() - trade_lock[symbol]

            if cooldown < 300:  # 5 minutes
                print(f"⏳ COOLDOWN ACTIVE: {symbol} ({int(300 - cooldown)}s left)")
                time.sleep(60)
                log_step("SKIP", f"{symbol} existing position")
                continue

        # =====================
        # RISK CHECK
        # =====================
        if not risk_guard(best["atr"], best["price"]):
            print("⚠ Market too volatile, skip trade")
            time.sleep(60)
            log_step("SKIP", f"{symbol} low score")
            continue

        balance = get_balance()

        # =====================
        # BALANCE CHECK
        # =====================
        if balance < MIN_BALANCE:
            print("⚠ Insufficient balance:", balance)
            time.sleep(60)
            log_step("SKIP", f"{symbol} low balance")
            continue

        step = get_step_size(symbol)
        leverage = smart_leverage(
        best["atr"],
        best["price"],
        balance
    )
        volatility = best["atr"] / best["price"]

        size = position_size(
        balance,
        best["price"],
        leverage,
        best["total_score"],
        volatility
    )
        size = adjust_quantity(size, step)

        balance = get_balance()
        log_step(
            "READY",
            f"{symbol} direction={best['direction']} score={best['total_score']:.2f}"
    )

        leverage = smart_leverage(best["atr"], best["price"], balance)

            # =====================
            # OPEN POSITION CHECK
            # =====================
        if TRADE_ENABLED:

            if has_open_position(symbol):
                print("⚠ Existing position:", symbol)
                time.sleep(60)
                log_step("SKIP", f"{symbol} existing position")
                continue

            # =====================
            # COOLDOWN CHECK
            # =====================
            if not can_trade(symbol):
                print("⏳ Cooldown active:", symbol)
                time.sleep(60)
                log_step("SKIP", f"{symbol} cooldown active")
                continue

            # =====================
            # LEVERAGE
            # =====================

            try:
                client.futures_change_leverage(
                    symbol=symbol,
                    leverage=leverage
                )
            except Exception as e:
                print("Leverage error:", e)

            print("Leverage used:", leverage)

            # =====================
            # FINAL SAFETY CHECK BEFORE EXECUTION
            # =====================
            if not can_afford_trade(size, best["price"], leverage):
                log_step("SKIP", f"{symbol} insufficient margin capacity")
                continue

            if trades_this_cycle >= MAX_TRADES_PER_CYCLE:
                log_step("SKIP", f"{symbol} cycle limit reached")
                continue

            # =====================
            # EXECUTE TRADE
            # =====================
            log_step(
                "EXECUTE",
                f"{symbol} {best['direction']} leverage={leverage} size={size}"
    )
            place_trade(
                symbol,
                best["direction"],
                size,
                best["price"],
                best["atr"]
        )

            trades_this_cycle += 1
             # =====================
            # DAILY LOSS UPDATE (FIXED)
            # =====================

            estimated_loss = (best["atr"] * 2) * size

            # update DAILY PNL
            daily_pnl -= estimated_loss

            print("📉 TRADE RISK LOGGED:", round(estimated_loss, 2))
            print("📉 DAILY PNL UPDATED:", round(daily_pnl, 2))

            last_trade_time[symbol] = datetime.datetime.now()
            trade_lock[symbol] = time.time()

        else:
            print("🟡 SAFE MODE (no trade executed)")
        log_step(
            "SUMMARY",
            f"cycle done | trades={trades_this_cycle} | best_score={best_score}"
        )

    time.sleep(60)