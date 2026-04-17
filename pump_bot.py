import os
import json
import requests
import pandas as pd
from datetime import datetime, timedelta

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
MIN_15M_CHANGE = 0.8
MIN_VOL = 1.2

TP = 2.5
SL = 1.2

SIGNAL_FILE = "signals.json"

# =========================
# JSON
# =========================
def load_signals():
    try:
        with open(SIGNAL_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_signals(data):
    with open(SIGNAL_FILE, "w") as f:
        json.dump(data, f)

# =========================
# BINANCE DATA
# =========================
def get_top_movers():
    data = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()

    coins = []
    for c in data:
        if "USDT" not in c["symbol"]:
            continue

        coins.append({
            "symbol": c["symbol"],
            "change": float(c["priceChangePercent"])
        })

    gainers = sorted(coins, key=lambda x: x["change"], reverse=True)[:15]
    losers = sorted(coins, key=lambda x: x["change"])[:15]

    return gainers + losers

def get_price(symbol):
    r = requests.get("https://fapi.binance.com/fapi/v1/ticker/price",
                     params={"symbol": symbol})
    if r.status_code != 200:
        return None
    return float(r.json()["price"])

def get_klines(symbol):
    r = requests.get("https://fapi.binance.com/fapi/v1/klines",
                     params={"symbol": symbol, "interval": "15m", "limit": 50})

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

    change_15m = ((last["close"] - prev["close"]) / prev["close"]) * 100

    vol_avg = df["volume"].rolling(20).mean().iloc[-1]
    vol_ratio = last["volume"] / vol_avg if vol_avg else 0

    up = last["close"] > df["close"].iloc[-3]
    down = last["close"] < df["close"].iloc[-3]

    return {
        "price": last["close"],
        "change_15m": change_15m,
        "vol": vol_ratio,
        "up": up,
        "down": down
    }

# =========================
# AKILLI SİNYAL
# =========================
def smart_signal(d, daily):

    if daily > 5 and d["change_15m"] > 0 and d["vol"] > 1.3:
        return "LONG"

    if daily < -5 and d["change_15m"] < 0 and d["vol"] > 1.3:
        return "SHORT"

    if daily > 8 and d["change_15m"] < 0:
        return "SHORT REVERSAL"

    if daily < -8 and d["change_15m"] > 0:
        return "LONG REVERSAL"

    return None

# =========================
# TP SL
# =========================
def levels(price, signal):
    if "LONG" in signal:
        tp = price * (1 + TP/100)
        sl = price * (1 - SL/100)
    else:
        tp = price * (1 - TP/100)
        sl = price * (1 + SL/100)
    return tp, sl

# =========================
# TAKİP
# =========================
def check_old_signals():
    signals = load_signals()
    results = []

    for k, s in signals.items():
        if s["done"]:
            continue

        t = datetime.fromisoformat(s["time"])

        if datetime.now() - t < timedelta(minutes=15):
            continue

        price = get_price(s["coin"])
        if not price:
            continue

        result = "DEVAM"

        if "LONG" in s["signal"]:
            if price >= s["tp"]:
                result = "TP"
            elif price <= s["sl"]:
                result = "SL"

        else:
            if price <= s["tp"]:
                result = "TP"
            elif price >= s["sl"]:
                result = "SL"

        s["done"] = True
        s["result"] = result

        results.append((s["coin"], result))

    save_signals(signals)
    return results

# =========================
# PANEL
# =========================
def panel():
    signals = load_signals()

    done = [s for s in signals.values() if s.get("done")]
    win = [s for s in done if s.get("result") == "TP"]

    total = len(done)
    wr = (len(win)/total)*100 if total else 0

    return f"📊 PANEL\nToplam: {total}\nWinrate: %{wr:.1f}"

# =========================
# MAIN
# =========================
def run():
    send("🚀 BOT ÇALIŞTI")

    # eski sonuçlar
    for coin, res in check_old_signals():
        send(f"📊 SONUÇ\n{coin} → {res}")

    coins = get_top_movers()
    signals = load_signals()

    new_count = 0

    for c in coins:
        sym = c["symbol"]
        daily = c["change"]

        d = analyze(sym)
        if not d:
            continue

        if abs(d["change_15m"]) < MIN_15M_CHANGE:
            continue

        if d["vol"] < MIN_VOL:
            continue

        signal = smart_signal(d, daily)
        if not signal:
            continue

        tp, sl = levels(d["price"], signal)

        send(f"🔥 SİNYAL\n{sym}\n{signal}\nEntry: {d['price']:.4f}")

        signals[sym + str(datetime.now())] = {
            "coin": sym,
            "entry": d["price"],
            "tp": tp,
            "sl": sl,
            "signal": signal,
            "time": datetime.now().isoformat(),
            "done": False
        }

        new_count += 1

    save_signals(signals)

    send(panel())
    send(f"📡 Yeni sinyal: {new_count}")

if __name__ == "__main__":
    run()
