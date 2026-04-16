import os
import json
from datetime import datetime, timedelta

import requests
import pandas as pd

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BASE_URL = "https://api.binance.com"

# ANA AYARLAR
SCAN_INTERVAL_NAME = "15m"
COOLDOWN_MINUTES = 180
ALERT_STATE_FILE = "alert_state.json"
SIGNAL_HISTORY_FILE = "signal_history.json"

# TRADINGVIEW AYARLARIN
RSI_LEN = 14
ADX_LEN = 14
EMA_FAST_LEN = 20
EMA_MID_LEN = 50
EMA_SLOW_LEN = 200
ATR_LEN = 14
VOL_LEN = 20

# Senin ekranda verdiğin ayar
PIVOT_LEN = 40

ADX_TREND_MIN = 22
HARD_DROP_ATR = 2.3
TREND_PCT_BUY = 60
TREND_PCT_SELL = 40

DIP_RSI_MAX = 38
TEPE_RSI_MIN = 62

VOL_MULTIPLIER_SIGNAL = 1.3
VOL_MULTIPLIER_TREND = 1.2

REQUEST_TIMEOUT = 20
LIMIT_15M = 320
LIMIT_1H = 320
LIMIT_4H = 320

MAX_SYMBOLS = 1000  # tüm coinler için yüksek tuttum


def load_json_file(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_alert_state():
    return load_json_file(ALERT_STATE_FILE, {})


def save_alert_state(state):
    save_json_file(ALERT_STATE_FILE, state)


def load_signal_history():
    return load_json_file(SIGNAL_HISTORY_FILE, [])


def save_signal_history(history):
    save_json_file(SIGNAL_HISTORY_FILE, history)


def append_signal_history(record):
    history = load_signal_history()
    history.append(record)
    if len(history) > 1000:
        history = history[-1000:]
    save_signal_history(history)


def can_send_alert(key, state):
    last_time_str = state.get(key)
    if not last_time_str:
        return True

    try:
        last_time = datetime.fromisoformat(last_time_str)
    except Exception:
        return True

    return datetime.utcnow() >= last_time + timedelta(minutes=COOLDOWN_MINUTES)


def mark_alert_sent(key, state):
    state[key] = datetime.utcnow().isoformat()
    save_alert_state(state)


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True
    }

    r = requests.post(url, json=payload, timeout=15)
    print("Telegram:", r.status_code, r.text[:250])


def binance_get(path, params=None):
    url = f"{BASE_URL}{path}"
    r = requests.get(url, params=params or {}, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_all_symbols():
    data = binance_get("/api/v3/exchangeInfo")
    symbols = []

    for row in data.get("symbols", []):
        symbol = row.get("symbol", "")
        status = row.get("status", "")
        quote_asset = row.get("quoteAsset", "")
        is_spot_allowed = row.get("isSpotTradingAllowed", False)

        if (
            status == "TRADING"
            and quote_asset == "USDT"
            and is_spot_allowed
        ):
            symbols.append(symbol)

    blocked = {
        "USDTRY", "EURUSDT", "TUSDUSDT", "FDUSDUSDT", "USDCUSDT", "BUSDUSDT"
    }
    symbols = [s for s in symbols if s not in blocked]

    return symbols[:MAX_SYMBOLS]


def get_klines(symbol, interval, limit):
    data = binance_get("/api/v3/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "number_of_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]

    df = pd.DataFrame(data, columns=cols)
    if df.empty:
        return df

    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

    # Açık son mumun sinyali bozmasını önlemek için son mumu çıkar
    if len(df) > 10:
        df = df.iloc[:-1].copy()

    df.reset_index(drop=True, inplace=True)
    return df


def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def rsi(series, length=14):
    delta = series.diff()

    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)

    avg_gain = gain.ewm(alpha=1 / length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, pd.NA)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def atr(df, length=14):
    prev_close = df["close"].shift(1)
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - prev_close).abs()
    tr3 = (df["low"] - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / length, adjust=False).mean()


def macd(series, fast=12, slow=26, signal=9):
    fast_ema = ema(series, fast)
    slow_ema = ema(series, slow)
    macd_line = fast_ema - slow_ema
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def adx(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    plus_dm[(up_move > down_move) & (up_move > 0)] = up_move
    minus_dm[(down_move > up_move) & (down_move > 0)] = down_move

    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    trur = tr.ewm(alpha=1 / length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, adjust=False).mean() / trur.replace(0, pd.NA)
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, adjust=False).mean() / trur.replace(0, pd.NA)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
    adx_line = dx.ewm(alpha=1 / length, adjust=False).mean()

    return adx_line.fillna(0), plus_di.fillna(0), minus_di.fillna(0)


def add_indicators(df):
    if df.empty:
        return df

    df = df.copy()
    df["ema20"] = ema(df["close"], EMA_FAST_LEN)
    df["ema50"] = ema(df["close"], EMA_MID_LEN)
    df["ema200"] = ema(df["close"], EMA_SLOW_LEN)

    df["rsi"] = rsi(df["close"], RSI_LEN)
    df["atr"] = atr(df, ATR_LEN)
    df["volMa"] = df["volume"].rolling(VOL_LEN).mean()

    macd_line, macd_signal, _ = macd(df["close"], 12, 26, 9)
    df["macdLine"] = macd_line
    df["macdSignal"] = macd_signal

    adx_line, plus_di, minus_di = adx(df, ADX_LEN)
    df["adx"] = adx_line
    df["plusDI"] = plus_di
    df["minusDI"] = minus_di

    return df


def trend_score(df):
    if df.empty or len(df) < 5:
        return None

    row = df.iloc[-1]

    score = 0
    score += 1 if row["ema20"] > row["ema50"] else -1
    score += 1 if row["ema50"] > row["ema200"] else -1
    score += 1 if row["close"] > row["ema20"] else -1
    score += 1 if row["rsi"] > 50 else -1
    score += 1 if row["macdLine"] > row["macdSignal"] else -1
    score += 1 if row["adx"] > ADX_TREND_MIN else 0
    return score


def calc_trend_pct(df):
    row = df.iloc[-1]

    local_score = 0.0
    local_score += 1 if row["ema20"] > row["ema50"] else -1
    local_score += 1 if row["ema50"] > row["ema200"] else -1
    local_score += 1 if row["close"] > row["ema20"] else -1
    local_score += 1 if row["rsi"] > 50 else -1
    local_score += 1 if row["macdLine"] > row["macdSignal"] else -1
    local_score += 1 if row["adx"] > ADX_TREND_MIN else 0
    local_score += 1 if row["volume"] > row["volMa"] * VOL_MULTIPLIER_TREND else -1

    trend_pct = round(50 + (local_score / 7 * 50))
    return int(trend_pct)


def pivot_low_confirmed(low_values, left, right):
    out = [False] * len(low_values)
    n = len(low_values)

    for i in range(left, n - right):
        center = low_values[i]
        window = low_values[i - left:i + right + 1]
        if pd.isna(center):
            continue
        if center == min(window):
            confirm_index = i + right
            if confirm_index < n:
                out[confirm_index] = True

    return pd.Series(out)


def pivot_high_confirmed(high_values, left, right):
    out = [False] * len(high_values)
    n = len(high_values)

    for i in range(left, n - right):
        center = high_values[i]
        window = high_values[i - left:i + right + 1]
        if pd.isna(center):
            continue
        if center == max(window):
            confirm_index = i + right
            if confirm_index < n:
                out[confirm_index] = True

    return pd.Series(out)


def analyze_symbol(symbol):
    try:
        df15 = add_indicators(get_klines(symbol, "15m", LIMIT_15M))
        df1h = add_indicators(get_klines(symbol, "1h", LIMIT_1H))
        df4h = add_indicators(get_klines(symbol, "4h", LIMIT_4H))
    except Exception as e:
        print(f"{symbol} veri çekme hatası: {e}")
        return None

    if df15.empty or df1h.empty or df4h.empty:
        return None

    min_needed = max(EMA_SLOW_LEN + PIVOT_LEN + 10, 260)
    if len(df15) < min_needed or len(df1h) < 220 or len(df4h) < 220:
        return None

    score15 = trend_score(df15)
    score1h = trend_score(df1h)
    score4h = trend_score(df4h)

    if score15 is None or score1h is None or score4h is None:
        return None

    mtf_bull = score15 >= 3 and score1h >= 3 and score4h >= 2
    mtf_bear = score15 <= -3 and score1h <= -3 and score4h <= -2
    trend_pct = calc_trend_pct(df15)

    df15["pivotLowConfirmed"] = pivot_low_confirmed(df15["low"].tolist(), PIVOT_LEN, PIVOT_LEN)
    df15["pivotHighConfirmed"] = pivot_high_confirmed(df15["high"].tolist(), PIVOT_LEN, PIVOT_LEN)

    df15["dipCond"] = df15["pivotLowConfirmed"] & (df15["rsi"].shift(PIVOT_LEN) < DIP_RSI_MAX)
    df15["tepeCond"] = df15["pivotHighConfirmed"] & (df15["rsi"].shift(PIVOT_LEN) > TEPE_RSI_MIN)

    df15["buySignal"] = (
        df15["dipCond"].shift(2).fillna(False)
        & mtf_bull
        & (trend_pct >= TREND_PCT_BUY)
        & (df15["close"] > df15["ema20"])
        & (df15["macdLine"] > df15["macdSignal"])
        & (df15["volume"] > df15["volMa"] * VOL_MULTIPLIER_SIGNAL)
    )

    df15["sellSignal"] = (
        df15["tepeCond"].shift(2).fillna(False)
        & mtf_bear
        & (trend_pct <= TREND_PCT_SELL)
        & (df15["close"] < df15["ema20"])
        & (df15["macdLine"] < df15["macdSignal"])
        & (df15["volume"] > df15["volMa"] * VOL_MULTIPLIER_SIGNAL)
    )

    last = df15.iloc[-1]

    side = None
    if bool(last["buySignal"]):
        side = "AL"
    elif bool(last["sellSignal"]):
        side = "SAT"
    else:
        return None

    price = float(last["close"])
    rsi_now = float(last["rsi"])
    adx_now = float(last["adx"])
    trend_name = "YÜKSELİŞ" if mtf_bull else "DÜŞÜŞ" if mtf_bear else "KARARSIZ"

    tv_pair = f"BINANCE:{symbol}"

    text = (
        f"{'🟢' if side == 'AL' else '🔴'} {side} SİNYALİ\n"
        f"Coin: {symbol}\n"
        f"Zaman: {SCAN_INTERVAL_NAME}\n"
        f"Fiyat: {price:.8f}\n"
        f"Trend: {trend_name}\n"
        f"Trend %: {trend_pct}\n"
        f"RSI: {rsi_now:.2f}\n"
        f"ADX: {adx_now:.2f}\n"
        f"TradingView: {tv_pair}"
    )

    record = {
        "timestamp_utc": datetime.utcnow().isoformat(),
        "symbol": symbol,
        "side": side,
        "timeframe": SCAN_INTERVAL_NAME,
        "price": round(price, 8),
        "trend_pct": trend_pct,
        "rsi": round(rsi_now, 4),
        "adx": round(adx_now, 4),
        "tradingview": tv_pair,
    }

    return side, text, record


def run_once():
    symbols = get_all_symbols()
    print(f"Toplam taranacak coin: {len(symbols)}")

    send_telegram(f"✅ Bot aktif, tarama başlıyor.\nTaranacak coin sayısı: {len(symbols)}")

    state = load_alert_state()
    found = 0

    for i, symbol in enumerate(symbols, start=1):
        print(f"[{i}/{len(symbols)}] {symbol} taranıyor...")
        try:
            result = analyze_symbol(symbol)
        except Exception as e:
            print(f"{symbol} analiz hatası: {e}")
            continue

        if not result:
            continue

        side, text, record = result
        key = f"{symbol}_{side}"

        if can_send_alert(key, state):
            send_telegram(text)
            append_signal_history(record)
            mark_alert_sent(key, state)
            found += 1
            print(f"Sinyal gönderildi: {symbol} - {side}")
        else:
            print(f"Cooldown aktif: {symbol} - {side}")

    print(f"Toplam gönderilen sinyal: {found}")


if __name__ == "__main__":
    run_once()
