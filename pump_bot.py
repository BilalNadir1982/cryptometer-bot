import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import requests

BINANCE_FAPI_BASE = "https://fapi.binance.com"
ISTANBUL_TZ = ZoneInfo("Europe/Istanbul")

CONFIG_FILE = "config.json"
STATE_FILE = "state.json"
SIGNALS_FILE = "signals.json"
RESULTS_FILE = "results.json"

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "pro-futures-signal-bot/1.0"})


def load_json(path, default):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config():
    cfg = load_json(CONFIG_FILE, None)
    if not cfg:
        raise FileNotFoundError("config.json bulunamadı.")
    return cfg


def now_utc():
    return datetime.now(timezone.utc)


def now_local():
    return datetime.now(ISTANBUL_TZ)


def safe_float(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default


def send_telegram(token, chat_id, text):
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        r = SESSION.post(url, json=payload, timeout=20)
        return r.status_code, r.text
    except Exception as e:
        return 0, str(e)


def get_futures_24h_tickers():
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/24hr"
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return data


def get_klines(symbol, interval="15m", limit=220):
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/klines"
    params = {"symbol": symbol, "interval": interval, "limit": limit}
    r = SESSION.get(url, params=params, timeout=20)
    r.raise_for_status()
    rows = r.json()

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "quote_asset_volume", "num_trades",
        "taker_buy_base", "taker_buy_quote", "ignore"
    ]
    df = pd.DataFrame(rows, columns=cols)
    for c in ["open", "high", "low", "close", "volume", "quote_asset_volume", "taker_buy_base", "taker_buy_quote"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)
    return df


def get_last_funding_rate(symbol):
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/fundingRate"
    params = {"symbol": symbol, "limit": 1}
    try:
        r = SESSION.get(url, params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list) and data:
            return safe_float(data[-1].get("fundingRate", 0.0))
    except Exception:
        pass
    return 0.0


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


def prepare_indicators(df):
    df = df.copy()
    df["ema50"] = ema(df["close"], 50)
    df["ema200"] = ema(df["close"], 200)
    df["rsi14"] = rsi(df["close"], 14)
    df["macd"], df["macd_signal"], df["macd_hist"] = macd(df["close"])
    df["atr14"] = atr(df, 14)
    df["vol_ma20"] = df["volume"].rolling(20).mean()
    df["ret_5"] = (df["close"] / df["close"].shift(5) - 1) * 100.0
    return df


def determine_signal(df, symbol):
    """
    Son kapalı mum = -2
    Anlık oluşan mum = -1
    """
    if len(df) < 210:
        return None

    d = prepare_indicators(df)
    last = d.iloc[-2]
    prev = d.iloc[-3]

    trend_up = last["ema50"] > last["ema200"]
    trend_down = last["ema50"] < last["ema200"]

    macd_cross_up = prev["macd"] <= prev["macd_signal"] and last["macd"] > last["macd_signal"]
    macd_cross_down = prev["macd"] >= prev["macd_signal"] and last["macd"] < last["macd_signal"]

    volume_burst = (
        pd.notna(last["vol_ma20"]) and last["vol_ma20"] > 0 and last["volume"] > last["vol_ma20"] * 2.0
    )

    momentum_up = safe_float(last["ret_5"]) > 1.8
    momentum_down = safe_float(last["ret_5"]) < -1.8

    funding = get_last_funding_rate(symbol)

    close_price = safe_float(last["close"])
    atr_val = safe_float(last["atr14"])

    if close_price <= 0 or atr_val <= 0:
        return None

    long_score = 0
    short_score = 0
    reasons_long = []
    reasons_short = []

    # RSI
    if last["rsi14"] <= 32:
        long_score += 2
        reasons_long.append(f"RSI dip ({last['rsi14']:.1f})")
    elif last["rsi14"] < 40:
        long_score += 1
        reasons_long.append(f"RSI zayıf dip ({last['rsi14']:.1f})")

    if last["rsi14"] >= 68:
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
        long_score += 3
        short_score += 3
        reasons_long.append("Hacim patlaması")
        reasons_short.append("Hacim patlaması")

    # Momentum
    if momentum_up:
        long_score += 2
        reasons_long.append(f"Momentum güçlü (+{last['ret_5']:.2f}%)")
    if momentum_down:
        short_score += 2
        reasons_short.append(f"Momentum güçlü ({last['ret_5']:.2f}%)")

    # Funding
    # Negatif funding => long lehine
    # Pozitif funding => short lehine
    if funding < 0:
        long_score += 1
        reasons_long.append(f"Funding avantajı ({funding:.5f})")
    elif funding > 0:
        short_score += 1
        reasons_short.append(f"Funding avantajı ({funding:.5f})")

    direction = None
    score = 0
    reasons = []

    if long_score > short_score and long_score >= 6:
        direction = "LONG"
        score = long_score
        reasons = reasons_long
    elif short_score > long_score and short_score >= 6:
        direction = "SHORT"
        score = short_score
        reasons = reasons_short
    else:
        return None

    strength = "GÜÇLÜ" if score >= 8 else "ORTA"
    entry = close_price

    if direction == "LONG":
        tp = entry + atr_val * CONFIG["tp_atr_multiplier"]
        sl = entry - atr_val * CONFIG["sl_atr_multiplier"]
    else:
        tp = entry - atr_val * CONFIG["tp_atr_multiplier"]
        sl = entry + atr_val * CONFIG["sl_atr_multiplier"]

    return {
        "symbol": symbol,
        "direction": direction,
        "strength": strength,
        "score": int(score),
        "entry": round(entry, 6),
        "tp": round(tp, 6),
        "sl": round(sl, 6),
        "atr": round(atr_val, 6),
        "rsi": round(safe_float(last["rsi14"]), 2),
        "funding": funding,
        "close_time": last["close_time"].isoformat(),
        "reasons": reasons[:5],
        "status": "OPEN",
        "updates_sent": [],
        "result": None
    }


def format_signal_message(sig):
    emoji = "🚀" if sig["direction"] == "LONG" else "🔻"
    return (
        f"{emoji} <b>{sig['symbol']} {sig['direction']}</b>\n\n"
        f"Güç: <b>{sig['strength']}</b>\n"
        f"Skor: <b>{sig['score']}/10</b>\n\n"
        f"Giriş: <code>{sig['entry']}</code>\n"
        f"TP: <code>{sig['tp']}</code>\n"
        f"SL: <code>{sig['sl']}</code>\n"
        f"RSI: <code>{sig['rsi']}</code>\n"
        f"Funding: <code>{sig['funding']:.5f}</code>\n\n"
        f"Nedenler:\n- " + "\n- ".join(sig["reasons"])
    )


def format_followup_message(symbol, minutes_passed, status, current_price, sig):
    icon = "✅" if "TP" in status else ("❌" if "SL" in status else "⏳")
    return (
        f"{icon} <b>Takip | {symbol}</b>\n\n"
        f"Süre: <b>{minutes_passed} dk</b>\n"
        f"Yön: <b>{sig['direction']}</b>\n"
        f"Durum: <b>{status}</b>\n"
        f"Anlık fiyat: <code>{current_price}</code>\n"
        f"Giriş: <code>{sig['entry']}</code>\n"
        f"TP: <code>{sig['tp']}</code>\n"
        f"SL: <code>{sig['sl']}</code>"
    )


def format_daily_summary(results, local_date_str):
    today_results = [r for r in results if r.get("closed_local_date") == local_date_str]
    total = len(today_results)
    wins = sum(1 for r in today_results if r.get("result") == "TP")
    losses = sum(1 for r in today_results if r.get("result") == "SL")
    open_count = sum(1 for r in today_results if r.get("result") == "OPEN")
    winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

    strong_count = sum(1 for r in today_results if r.get("strength") == "GÜÇLÜ")
    medium_count = sum(1 for r in today_results if r.get("strength") == "ORTA")

    return (
        f"📊 <b>Günlük Performans Özeti</b>\n"
        f"Tarih: <b>{local_date_str}</b>\n\n"
        f"Toplam sinyal: <b>{total}</b>\n"
        f"Kazanan: <b>{wins}</b>\n"
        f"Kaybeden: <b>{losses}</b>\n"
        f"Açık kalan: <b>{open_count}</b>\n"
        f"Winrate: <b>{winrate:.1f}%</b>\n\n"
        f"Güçlü sinyal: <b>{strong_count}</b>\n"
        f"Orta sinyal: <b>{medium_count}</b>"
    )


def symbol_allowed(t):
    symbol = t.get("symbol", "")
    if not symbol.endswith("USDT"):
        return False
    if "_" in symbol:
        return False
    if safe_float(t.get("quoteVolume")) < CONFIG["min_quote_volume_usdt"]:
        return False
    if abs(safe_float(t.get("priceChangePercent"))) < CONFIG["min_price_change_percent_24h"]:
        return False
    if symbol in set(CONFIG.get("exclude_symbols", [])):
        return False
    return True


def select_symbols(tickers):
    includes = CONFIG.get("include_symbols", [])
    if includes:
        return includes

    filtered = [t for t in tickers if symbol_allowed(t)]
    filtered.sort(key=lambda x: safe_float(x.get("quoteVolume")), reverse=True)
    return [t["symbol"] for t in filtered[: CONFIG["max_symbols"]]]


def should_scan_new_candle(state):
    """
    Aynı 15m kapanışı için bir kez çalışsın.
    """
    now = now_utc()
    minute_block = (now.minute // 15) * 15
    current_block = now.replace(minute=minute_block, second=0, microsecond=0)
    # kapalı mum için son block
    closed_candle_mark = current_block.isoformat()
    if state.get("last_scan_block") == closed_candle_mark:
        return False, closed_candle_mark
    return True, closed_candle_mark


def minutes_since(iso_dt):
    dt = datetime.fromisoformat(iso_dt)
    return int((now_utc() - dt).total_seconds() // 60)


def get_current_price(symbol):
    url = f"{BINANCE_FAPI_BASE}/fapi/v1/ticker/price"
    r = SESSION.get(url, params={"symbol": symbol}, timeout=20)
    r.raise_for_status()
    data = r.json()
    return safe_float(data.get("price"))


def evaluate_signal_status(sig, current_price):
    direction = sig["direction"]
    tp = sig["tp"]
    sl = sig["sl"]

    if direction == "LONG":
        if current_price >= tp:
            return "TP"
        if current_price <= sl:
            return "SL"
    else:
        if current_price <= tp:
            return "TP"
        if current_price >= sl:
            return "SL"
    return "OPEN"


def cooldown_ok(state, symbol):
    last_sent = state.get("cooldowns", {}).get(symbol)
    if not last_sent:
        return True
    dt = datetime.fromisoformat(last_sent)
    return (now_utc() - dt).total_seconds() >= CONFIG["cooldown_minutes"] * 60


def add_cooldown(state, symbol):
    state.setdefault("cooldowns", {})[symbol] = now_utc().isoformat()


def save_result_from_signal(sig, result):
    results = load_json(RESULTS_FILE, [])
    local_date = now_local().strftime("%Y-%m-%d")
    rec = {
        "symbol": sig["symbol"],
        "direction": sig["direction"],
        "strength": sig["strength"],
        "score": sig["score"],
        "entry": sig["entry"],
        "tp": sig["tp"],
        "sl": sig["sl"],
        "result": result,
        "closed_local_date": local_date,
        "close_time_utc": now_utc().isoformat()
    }
    results.append(rec)
    save_json(RESULTS_FILE, results)


def process_followups():
    signals = load_json(SIGNALS_FILE, [])
    updated = False

    for sig in signals:
        if sig.get("status") != "OPEN":
            continue

        symbol = sig["symbol"]
        try:
            current_price = get_current_price(symbol)
        except Exception:
            continue

        live_status = evaluate_signal_status(sig, current_price)
        if live_status in ["TP", "SL"]:
            sig["status"] = live_status
            sig["result"] = live_status
            save_result_from_signal(sig, live_status)
            updated = True

        passed = minutes_since(sig["close_time"])
        for mark in [15, 30, 60]:
            key = str(mark)
            if passed >= mark and key not in sig["updates_sent"]:
                msg_status = live_status if live_status != "OPEN" else "Hâlâ açık"
                send_telegram(
                    CONFIG["telegram_bot_token"],
                    CONFIG["telegram_chat_id"],
                    format_followup_message(symbol, mark, msg_status, current_price, sig)
                )
                sig["updates_sent"].append(key)
                updated = True

    if updated:
        save_json(SIGNALS_FILE, signals)


def send_daily_summary_if_needed(state):
    hour = CONFIG["summary_hour_istanbul"]
    local_now = now_local()
    today_key = local_now.strftime("%Y-%m-%d")

    if local_now.hour < hour:
        return

    if state.get("daily_summary_sent_for") == today_key:
        return

    results = load_json(RESULTS_FILE, [])
    message = format_daily_summary(results, today_key)
    send_telegram(CONFIG["telegram_bot_token"], CONFIG["telegram_chat_id"], message)
    state["daily_summary_sent_for"] = today_key


def scan_market():
    tickers = get_futures_24h_tickers()
    symbols = select_symbols(tickers)

    sent_count = 0
    state = load_json(STATE_FILE, {})
    open_signals = load_json(SIGNALS_FILE, [])

    for symbol in symbols:
        if not cooldown_ok(state, symbol):
            continue

        try:
            df = get_klines(symbol, interval="15m", limit=220)
            sig = determine_signal(df, symbol)
            if not sig:
                continue

            text = format_signal_message(sig)
            code, resp = send_telegram(CONFIG["telegram_bot_token"], CONFIG["telegram_chat_id"], text)

            if code == 200:
                open_signals.append(sig)
                add_cooldown(state, symbol)
                sent_count += 1
            else:
                print(f"Telegram hata {symbol}: {code} | {resp}")

        except Exception as e:
            print(f"{symbol} hata: {e}")

    save_json(SIGNALS_FILE, open_signals)
    save_json(STATE_FILE, state)
    return sent_count, symbols


def bootstrap_files():
    if not os.path.exists(STATE_FILE):
        save_json(STATE_FILE, {"cooldowns": {}})
    if not os.path.exists(SIGNALS_FILE):
        save_json(SIGNALS_FILE, [])
    if not os.path.exists(RESULTS_FILE):
        save_json(RESULTS_FILE, [])


def main():
    global CONFIG
    CONFIG = load_config()
    bootstrap_files()

    state = load_json(STATE_FILE, {"cooldowns": {}})

    # Önce takipleri işle
    process_followups()

    # Günlük özet
    send_daily_summary_if_needed(state)

    # Yeni 15m blokta tarama
    do_scan, block = should_scan_new_candle(state)
    if not do_scan:
        print("Bu 15m blok için tarama zaten yapıldı.")
        save_json(STATE_FILE, state)
        return

    try:
        sent_count, symbols = scan_market()
        msg = (
            f"🤖 Bot taraması tamamlandı\n"
            f"Tarama adedi: {len(symbols)}\n"
            f"Üretilen sinyal: {sent_count}\n"
            f"Zaman: {now_local().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        send_telegram(CONFIG["telegram_bot_token"], CONFIG["telegram_chat_id"], msg)

        state["last_scan_block"] = block
        save_json(STATE_FILE, state)

    except Exception as e:
        err = f"❌ Bot hata verdi:\n<code>{str(e)}</code>"
        send_telegram(CONFIG["telegram_bot_token"], CONFIG["telegram_chat_id"], err)
        raise


if __name__ == "__main__":
    main()
