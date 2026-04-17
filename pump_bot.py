import os
import json
from datetime import datetime, timedelta

import pandas as pd
import requests

# =========================
# TELEGRAM
# =========================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def send(msg):
    requests.post(
        f"https://api.telegram.org/bot{TOKEN}/sendMessage",
        data={"chat_id": CHAT_ID, "text": msg}
    )

# =========================
# AYARLAR
# =========================
MIN_CHANGE = 1.2
MIN_VOL = 1.3
MAX_COINS = 25

TP = 2.0
SL = -1.0

COOLDOWN_MIN = 60

SIGNAL_FILE = "signals.json"
COOLDOWN_FILE = "cooldown.json"

# =========================
# JSON
# =========================
def load(file):
    try:
        with open(file) as f:
            return json.load(f)
    except:
        return {}

def save(file, data):
    with open(file, "w") as f:
        json.dump(data, f)

# =========================
# COOLDOWN
# =========================
def is_cooldown(symbol, cd):
    if symbol not in cd:
        return False
    return datetime.now() - datetime.fromisoformat(cd[symbol]) < timedelta(minutes=COOLDOWN_MIN)

def set_cooldown(symbol, cd):
    cd[symbol] = datetime.now().isoformat()

# =========================
# COIN
# =========================
def get_coins():
    data = requests.get(
        "https://api.coingecko.com/api/v3/coins/markets",
        params={"vs_currency": "usd", "order": "volume_desc", "per_page": 100}
    ).json()

    return [c["symbol"].upper() for c in data][:MAX_COINS]

# =========================
# MARKET
# =========================
def get_price(symbol):
    r = requests.get("https://api.binance.com/api/v3/ticker/price",
                     params={"symbol": f"{symbol}USDT"})
    if r.status_code != 200:
        return None
    return float(r.json()["price"])

def get_klines(symbol):
    r = requests.get("https://api.binance.com/api/v3/klines",
                     params={"symbol": f"{symbol}USDT", "interval": "15m", "limit": 50})

    if r.status_code != 200:
        return None

    df = pd.DataFrame(r.json())
    df = df[[4,5]]
    df.columns = ["close","volume"]
    return df.astype(float)

# =========================
# ANALİZ
# =========================
def analyze(symbol):
    df = get_klines(symbol)
    if df is None or len(df) < 30:
        return None

    last = df.iloc[-1]
    prev = df.iloc[-2]

    change = ((last["close"] - prev["close"]) / prev["close"]) * 100
    vol_avg = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = last["volume"] / vol_avg if vol_avg else 0

    trend = df["close"].iloc[-1] > df["close"].iloc[-3]

    return {"price": last["close"], "change": change, "vol": vol_ratio, "trend": trend}

# =========================
# SİNYAL
# =========================
def is_signal(d):
    return d["change"] >= MIN_CHANGE and d["vol"] >= MIN_VOL and d["trend"]

# =========================
# TP SL
# =========================
def check_old(signals):
    results = []

    for k, s in signals.items():
        if s["done"]:
            continue

        if datetime.now() - datetime.fromisoformat(s["time"]) < timedelta(minutes=15):
            continue

        price = get_price(s["coin"])
        if not price:
            continue

        ch = ((price - s["entry"]) / s["entry"]) * 100

        if ch >= TP:
            res = "TP"
        elif ch <= SL:
            res = "SL"
        else:
            res = "DEVAM"

        s["done"] = True
        s["result"] = res

        results.append((s["coin"], res, ch))

    return results

# =========================
# PANEL
# =========================
def panel(signals, sent):
    done = [s for s in signals.values() if s.get("done")]
    win = [s for s in done if s.get("result") == "TP"]

    total = len(done)
    win_count = len(win)
    wr = (win_count / total * 100) if total else 0

    return (
        f"📊 BOT PANEL\n\n"
        f"Toplam sinyal: {len(signals)}\n"
        f"Sonuçlanan: {total}\n"
        f"Kazanan: {win_count}\n"
        f"Winrate: %{wr:.1f}\n\n"
        f"Bu tur sinyal: {sent}\n"
        f"Saat: {datetime.now().strftime('%H:%M:%S')}"
    )

# =========================
# MAIN
# =========================
def run():
    send("🚀 Bot aktif")

    cooldown = load(COOLDOWN_FILE)
    signals = load(SIGNAL_FILE)

    # eski sonuçlar
    for coin, res, ch in check_old(signals):
        send(f"📊 SONUÇ → {coin} {res} (%{ch:.2f})")

    coins = get_coins()
    sent = 0

    for coin in coins:
        if is_cooldown(coin, cooldown):
            continue

        d = analyze(coin)
        if not d or not is_signal(d):
            continue

        send(f"🔥 SİNYAL\n{coin}\n%{d['change']:.2f} | x{d['vol']:.2f}")

        signals[coin+str(datetime.now())] = {
            "coin": coin,
            "entry": d["price"],
            "time": datetime.now().isoformat(),
            "done": False
        }

        set_cooldown(coin, cooldown)
        sent += 1

    save(SIGNAL_FILE, signals)
    save(COOLDOWN_FILE, cooldown)

    send(panel(signals, sent))

if __name__ == "__main__":
    run()
