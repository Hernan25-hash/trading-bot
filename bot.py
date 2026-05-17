from binance.client import Client
from binance.enums import SIDE_BUY, SIDE_SELL
import pandas as pd
import numpy as np
import time
import datetime
from ta.momentum import RSIIndicator
from ta.trend import EMAIndicator
from ta.volatility import AverageTrueRange
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

    # default safety cap
    max_lev = 8
    min_lev = 1

    # 🧠 HIGH RISK MARKET
    if volatility > 0.015:
        lev = 1

    # ⚠️ VERY VOLATILE
    elif volatility > 0.01:
        lev = 2

    # 📊 NORMAL MARKET
    elif volatility > 0.006:
        lev = 3

    # 📈 GOOD MARKET CONDITION
    elif volatility > 0.003:
        lev = 5

    # 🟢 VERY CALM MARKET
    else:
        lev = 7

    # 💰 BALANCE ADJUSTMENT (important)
    if balance < 20:
        lev = min(2, lev)
    elif balance < 100:
        lev = min(5, lev)

    # 🛑 HARD LIMIT
    return max(min_lev, min(lev, max_lev))

# =====================
# API (TESTNET)
# =====================
api_key = "gM9HfSPottj0zvKicX1hg7z3a1GgKJTpq028n7ZOg7Parn3obXuZ083Zu4myPDWz"
api_secret = "tJC4LYQouXzJaLzB45DEXIFIVeFgi6cBZ0vqGnpMvS0JNxySYyEQJVoFBXiw1qd3"

client = Client(api_key, api_secret)
# client.FUTURES_URL = "https://testnet.binancefuture.com/fapi"

# =====================
# SETTINGS
# =====================
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT"]
TIMEFRAME = "5m"
RISK_PER_TRADE = 0.01

TRADE_ENABLED = True   # 🔴 SAFE MODE (set True kapag ready ka na)

MIN_BALANCE = 10 


print("SMART SNIPER BOT STARTED")
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

    df_5m = client.futures_klines(symbol=symbol, interval="5m", limit=50)
    df_15m = client.futures_klines(symbol=symbol, interval="15m", limit=50)
    df_1h = client.futures_klines(symbol=symbol, interval="1h", limit=50)
    df_4h = client.futures_klines(symbol=symbol, interval="4h", limit=50)
    df_1d = client.futures_klines(symbol=symbol, interval="1d", limit=50)

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
# =====================
# DATA
# =====================
def get_data(symbol):
    klines = client.futures_klines(symbol=symbol, interval=TIMEFRAME, limit=120)

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
        df = client.futures_klines(symbol=symbol, interval=tf, limit=50)

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

# =====================
# SCORING ENGINE
# =====================
def signal(df):
    data = analyze(df)

    price = data["price"]
    ema = data["ema"]
    rsi = data["rsi"]
    atr = data["atr"]
    vol_ratio = data["volatility"]

    chop = abs(price - ema) / ema
    trend_strength = chop

    # 🔥 EARLY EXIT FILTER
    if chop < 0.001:
        return {"score": 0, "direction": None, "price": price, "atr": atr}

    score = 0
    direction = None
    # =====================
    # TREND
    # =====================
    if price > ema:
        direction = "BUY"
        score += 2
    else:
        direction = "SELL"
        score += 2

    # =====================
    # TREND STRENGTH FILTER
    # =====================
    if trend_strength < 0.0015:
        score -= 2
    elif trend_strength > 0.006:
        score += 1

    # =====================
    # RSI FILTER
    # =====================
    if direction == "BUY" and rsi < 45:
        score += 2
    elif direction == "SELL" and rsi > 55:
        score += 2

    # =====================
    # VOLUME FILTER
    # =====================
    vol = df["volume"].iloc[-1]

    if vol > df["volume"].mean() * 1.2:
        score += 1

    # =====================
    # ATR FILTER
    # =====================
    if (atr / price) > 0.0008:
        score += 1

    # =====================
    # VOLATILITY FILTER (NEW)
    # =====================
    if vol_ratio > 0.01:
        score -= 2   # too dangerous
    elif vol_ratio < 0.003:
        score += 1   # stable market

    # =====================
    # CHOP FILTER
    # =====================
    if chop < 0.002:
        score -= 1
    elif chop > 0.01:
        score += 1

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
    return required_margin < available * 0.7
# =====================
# RISK GUARD (anti-high volatility filter)
# =====================
def risk_guard(atr, price):
    return (atr / price) < 0.02

# =====================
# POSITION SIZE (risk-based)
# =====================
def position_size(balance, price, atr):

    # 1. safety checks
    if balance <= 0 or price <= 0 or atr <= 0:
        return 0

    # 2. dynamic risk
    if balance < 20:
        risk_pct = 0.01
    elif balance < 100:
        risk_pct = 0.01
    else:
        risk_pct = 0.02

    risk_amount = balance * risk_pct

    # =====================
    # HARD SAFETY CAP (OPTION 3 FIX)
    # =====================
    max_notional = balance * 2   # max exposure allowed

    if risk_amount > max_notional:
        risk_amount = max_notional

    # 3. stop distance (ATR-based)
    stop_distance = atr * 2

    if stop_distance <= 0:
        return 0

    # 4. raw size
    size = risk_amount / stop_distance

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
    

# =====================
# MAIN LOOP (SNIPER MODE)
# =====================


while True:
    MAX_TRADES_PER_CYCLE = 1
    trades_this_cycle = 0

    # =====================
    # DAILY LOSS CHECK (FIX FIX)
    # =====================
    if not check_daily_loss():
        print("BOT STOPPED DUE TO LOSS LIMIT")
        break

    best = None
    best_score = -999

    for symbol in SYMBOLS:

        # =====================
        # SMART TIMEFRAME PICK
        # =====================
        tf = detect_timeframe(symbol)
        print(symbol, "selected TF:", tf)

        df = client.futures_klines(symbol=symbol, interval=tf, limit=120)

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

        volatility = data["atr"] / data["price"]

        # ❌ skip extreme volatility
        if volatility > 0.015:
            continue

        # ❌ skip dead market
        if volatility < 0.0003:
            continue

        # ❌ skip extreme RSI conditions
        if data["rsi"] > 80 or data["rsi"] < 20:
            continue

        # ❌ skip no-trend market
        if abs(data["ema"] - data["price"]) / data["price"] < 0.0008:
            continue

        sig = signal(df)

        if sig:

            tf_confirm = multi_tf_confirmation(symbol, sig["direction"])
            total_score = sig["score"] + tf_confirm

            print(
                symbol,
                "base score:", sig["score"],
                "TF confirm:", tf_confirm,
                "TOTAL:", total_score
            )

            if total_score > best_score:
                best_score = total_score

                best = {
                    "symbol": symbol,
                    **sig,
                    "tf": tf,
                    "tf_confirm": tf_confirm,
                    "total_score": total_score
                }

                print("\n🔥 NEW BEST SNIPER SIGNAL:", best)

    # =====================
    # TRADE CHECK
    # =====================
    if best and best["total_score"] >= 5:

        symbol = best["symbol"]

        # =====================
        # COOLDOWN CHECK (FIXED)
        # =====================
        if symbol in trade_lock:
            cooldown = time.time() - trade_lock[symbol]

            if cooldown < 300:  # 5 minutes
                print(f"⏳ COOLDOWN ACTIVE: {symbol} ({int(300 - cooldown)}s left)")
                time.sleep(60)
                continue

        # =====================
        # RISK CHECK
        # =====================
        if not risk_guard(best["atr"], best["price"]):
            print("⚠ Market too volatile, skip trade")
            time.sleep(60)
            continue

        balance = get_balance()

        # =====================
        # BALANCE CHECK
        # =====================
        if balance < MIN_BALANCE:
            print("⚠ Insufficient balance:", balance)
            time.sleep(60)
            continue

        step = get_step_size(symbol)
        size = position_size(balance, best["price"], best["atr"])
        size = adjust_quantity(size, step)

        print("READY SNIPER TRADE:", best)

            # =====================
            # OPEN POSITION CHECK
            # =====================
        if TRADE_ENABLED:

            if has_open_position(symbol):
                print("⚠ Existing position:", symbol)
                time.sleep(60)
                continue

            # =====================
            # COOLDOWN CHECK
            # =====================
            if not can_trade(symbol):
                print("⏳ Cooldown active:", symbol)
                time.sleep(60)
                continue

            # =====================
            # LEVERAGE
            # =====================
            leverage = smart_leverage(best["atr"], best["price"])

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
                print("⚠ SKIP: insufficient margin capacity")
                continue

            if trades_this_cycle >= MAX_TRADES_PER_CYCLE:
                print("⚠ CYCLE LIMIT REACHED")
                continue

            # =====================
            # EXECUTE TRADE
            # =====================
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

    time.sleep(60)