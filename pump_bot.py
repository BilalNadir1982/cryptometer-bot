import os
import time
import json
from datetime import datetime

import numpy as np
import pandas as pd
import requests

COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

BINANCE_BASE = "https://fapi.binance.com"
COINGECKO_BASE = "https://api.coingecko.com/api/v3"

session = requests.Session()
session.headers.update({"User-Agent": "free-max-crypto-signal-bot/1.0"})

STATE_FILE = "state.json"


def load_state():
    if not os.path.exists(STATE_FILE):
        return {"cooldowns": {}, "last_run_key": ""}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"cooldowns": {}, "last_run_key": ""}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram secret eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    r = session.post(url, json=payload, timeout=30)
    print("Telegram:", r.status_code, r.text[:200])


def cg_get(path, params=None):
    headers = {}
    if COINGECKO_API_KEY:
        headers["x-cg-demo-api-key"] = COINGECKO_API_KEY

    url = f"{COINGECKO_BASE}{path}"
    r = session.get(url, params=params or {}, headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()


def binance_get(path, params=None):
    url = f"{BINANCE_BASE}{path}"
    r = session.get(url, params=params or {}, timeout=30)
    r.raise_for_status()
    return r.json()


def get_candidate_coins():
    """
    CoinGecko'dan piyasa ilgisi yüksek coinleri çek.
    """
    data = cg_get(
        "/coins/markets",
        {
            "vs_currency": "usd",
            "order": "volume_desc",
            "per_page": 100,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d"
        }
    )

    out = []
    for row in data:
        symbol = str(row.get("symbol", "")).upper()
        if not symbol:
            continue

        vol = safe_float(row.get("total_volume"))
        ch24 = safe_float(row.get("price_change_percentage_24h"))
        ch1h = safe_float(row.get("price_change_percentage_1h_in_currency"))
        mcap = safe_float(row.get("market_cap"))

        # Aşırı küçük/çöp coinleri azalt
        if vol < 8_000_000:
            continue
        if mcap < 50_000_000:
            continue
        if abs(ch24) < 2.0 and abs(ch1h) < 0.8:
            continue

        out.append({
            "cg_id": row.get("id"),
            "symbol": f"{symbol}USDT",
            "base_symbol": symbol,
            "volume": vol,
            "change_24h": ch24,
            "change_1h": ch1h
        })

    # En hareketli ve hacimli coinler
    out.sort(key=lambda x: (abs(x["change_24h"]) + abs(x["change_1h"]), x["volume"]), reverse=True)
    return out[:25]


def get_binance_symbols():
    info = binance_get("/fapi/v1/exchangeInfo")
    symbols = set()
    for s in info.get("symbols", []):
        if s.get("status") == "TRADING" and s.get("contractType") == "PERPETUAL":
            symbols.add(s.get("symbol"))
    return symbols


def get_klines(symbol, interval="15m", limit=220):
    rows = binance_get("/fapi/v1/klines", {
        "symbol": symbol,
        "interval": interval,
        "limit": limit
    })

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(rows, columns=cols)

    for c in ["open", "high", "low", "close", "volume", "quote_asset_volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()


def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / length, min_periods=length, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def macd(series, fast=12, slow=26, signal=9):
    macd_line = ema(series, fast) - ema(series, slow)
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist


def atr(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)

    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs()
    ], axis=1).max(axis=1)

    return tr.rolling(length).mean()


def add_indicators(df):
    d = df.copy()
    d["ema50"] = ema(d["close"], 50)
    d["ema200"] = ema(d["close"], 200)
    d["rsi14"] = rsi(d["close"], 14)
    d["macd"], d["macd_signal"], d["macd_hist"] = macd(d["close"])
    d["atr14"] = atr(d, 14)
    d["vol_ma20"] = d["volume"].rolling(20).mean()
    d["ret_3"] = (d["close"] / d["close"].shift(3) - 1) * 100
    d["ret_5"] = (d["close"] / d["close"].shift(5) - 1) * 100
    return d


def cooldown_ok(state, symbol, minutes=60):
    last = state.get("cooldowns", {}).get(symbol)
    if not last:
        return True
    try:
        last_ts = pd.Timestamp(last)
        diff = (pd.Timestamp.utcnow() - last_ts).total_seconds() / 60
        return diff >= minutes
    except Exception:
        return True


def set_cooldown(state, symbol):
    state.setdefault("cooldowns", {})[symbol] = pd.Timestamp.utcnow().isoformat()


def build_signal(symbol, cg_meta):
    df = get_klines(symbol, "15m", 220)
    d = add_indicators(df)

    if len(d) < 210:
        return None

    last = d.iloc[-2]
    prev = d.iloc[-3]

    close_price = safe_float(last["close"])
    atr_val = safe_float(last["atr14"])
    if close_price <= 0 or atr_val <= 0:
        return None

    trend_up = last["ema50"] > last["ema200"]
    trend_down = last["ema50"] < last["ema200"]

    macd_cross_up = prev["macd"] <= prev["macd_signal"] and last["macd"] > last["macd_signal"]
    macd_cross_down = prev["macd"] >= prev["macd_signal"] and last["macd"] < last["macd_signal"]

    volume_burst = pd.notna(last["vol_ma20"]) and last["vol_ma20"] > 0 and last["volume"] > last["vol_ma20"] * 1.8
    pseudo_whale = pd.notna(last["vol_ma20"]) and last["vol_ma20"] > 0 and last["volume"] > last["vol_ma20"] * 2.5

    momentum_up = safe_float(last["ret_5"]) > 1.5
    momentum_down = safe_float(last["ret_5"]) < -1.5

    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    # CoinGecko piyasa ilgisi
    if abs(cg_meta["change_24h"]) >= 5:
        if cg_meta["change_24h"] > 0:
            long_score += 1
            reasons_long.append(f"CoinGecko 24s güçlü (+{cg_meta['change_24h']:.2f}%)")
        else:
            short_score += 1
            reasons_short.append(f"CoinGecko 24s güçlü ({cg_meta['change_24h']:.2f}%)")

    if abs(cg_meta["change_1h"]) >= 1:
        if cg_meta["change_1h"] > 0:
            long_score += 1
            reasons_long.append(f"CoinGecko 1s ivme (+{cg_meta['change_1h']:.2f}%)")
        else:
            short_score += 1
            reasons_short.append(f"CoinGecko 1s ivme ({cg_meta['change_1h']:.2f}%)")

    # RSI
    if last["rsi14"] <= 33:
        long_score += 2
        reasons_long.append(f"RSI dip ({last['rsi14']:.1f})")
    elif last["rsi14"] < 40:
        long_score += 1
        reasons_long.append(f"RSI zayıf dip ({last['rsi14']:.1f})")

    if last["rsi14"] >= 67:
        short_score += 2
        reasons_short.append(f"RSI tepe ({last['rsi14']:.1f})")
    elif last["rsi14"] > 60:
        short_score += 1
        reasons_short.append(f"RSI zayıf tepe ({last['rsi14']:.1f})")

    # MACD
    if macd_cross_up:
        long_score += 2
        reasons_long.append("MACD yukarı kesişim")
    elif last["macd"] > last["macd_signal"]:
        long_score += 1
        reasons_long.append("MACD pozitif")

    if macd_cross_down:
        short_score += 2
        reasons_short.append("MACD aşağı kesişim")
    elif last["macd"] < last["macd_signal"]:
        short_score += 1
        reasons_short.append("MACD negatif")

    # Trend
    if trend_up:
        long_score += 2
        reasons_long.append("EMA trend yukarı")
    if trend_down:
        short_score += 2
        reasons_short.append("EMA trend aşağı")

    # Hacim
    if volume_burst:
        long_score += 2
        short_score += 2
        reasons_long.append("Hacim patlaması")
        reasons_short.append("Hacim patlaması")

    # Pseudo whale
    if pseudo_whale:
        long_score += 2
        short_score += 2
        reasons_long.append("Pseudo whale hacim")
        reasons_short.append("Pseudo whale hacim")

    # Momentum
    if momentum_up:
        long_score += 2
        reasons_long.append(f"Momentum (+{last['ret_5']:.2f}%)")
    if momentum_down:
        short_score += 2
        reasons_short.append(f"Momentum ({last['ret_5']:.2f}%)")

    direction = None
    score = 0
    reasons = []

    if long_score > short_score and long_score >= 7:
        direction = "LONG"
        score = long_score
        reasons = reasons_long
    elif short_score > long_score and short_score >= 7:
        direction = "SHORT"
        score = short_score
        reasons = reasons_short
    else:
        return None

    strength = "GÜÇLÜ" if score >= 9 else "ORTA"

    if direction == "LONG":
        tp = close_price + atr_val * 2.0
        sl = close_price - atr_val * 1.1
    else:
        tp = close_price - atr_val * 2.0
        sl = close_price + atr_val * 1.1

    return {
        "symbol": symbol,
        "direction": direction,
        "strength": strength,
        "score": score,
        "entry": round(close_price, 6),
        "tp": round(tp, 6),
        "sl": round(sl, 6),
        "rsi": round(safe_float(last["rsi14"]), 2),
        "reasons": reasons[:6]
    }


def format_signal(sig):
    emoji = "🚀" if sig["direction"] == "LONG" else "🔻"
    return (
        f"{emoji} <b>{sig['symbol']} {sig['direction']}</b>\n\n"
        f"Güç: <b>{sig['strength']}</b>\n"
        f"Skor: <b>{sig['score']}/10</b>\n\n"
        f"Giriş: <code>{sig['entry']}</code>\n"
        f"TP: <code>{sig['tp']}</code>\n"
        f"SL: <code>{sig['sl']}</code>\n"
        f"RSI: <code>{sig['rsi']}</code>\n\n"
        f"Nedenler:\n- " + "\n- ".join(sig["reasons"])
    )


def run_key():
    now = datetime.utcnow()
    block = (now.minute // 15) * 15
    return now.strftime(f"%Y-%m-%d %H:{block:02d}")


def main():
    if not COINGECKO_API_KEY:
        raise RuntimeError("COINGECKO_API_KEY eksik")
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("Telegram secret eksik")

    state = load_state()
    rk = run_key()

    if state.get("last_run_key") == rk:
        print("Bu 15dk blokta zaten çalıştı.")
        return

    send_telegram("🤖 <b>Ücretsiz maksimum sistem taraması başladı</b>")

    candidates = get_candidate_coins()
    tradable = get_binance_symbols()

    sent = 0
    checked = 0

    for coin in candidates:
        symbol = coin["symbol"]

        if symbol not in tradable:
            continue
        if not cooldown_ok(state, symbol, 60):
            continue

        checked += 1

        try:
            sig = build_signal(symbol, coin)
            if sig:
                send_telegram(format_signal(sig))
                set_cooldown(state, symbol)
                sent += 1
            time.sleep(1.0)
        except Exception as e:
            print("Hata:", symbol, str(e))

    state["last_run_key"] = rk
    save_state(state)

    send_telegram(
        f"📊 <b>Tarama bitti</b>\n"
        f"Aday coin: <b>{len(candidates)}</b>\n"
        f"Kontrol edilen: <b>{checked}</b>\n"
        f"Sinyal: <b>{sent}</b>"
    )


if __name__ == "__main__":
    main()
