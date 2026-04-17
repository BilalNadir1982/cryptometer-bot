import os
import requests
import pandas as pd
from datetime import datetime

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

# =========================
# TOP GAINER / LOSER
# =========================
def get_top_movers():
    data = requests.get("https://fapi.binance.com/fapi/v1/ticker/24hr").json()

    coins = []
    for c in data:
        if "USDT" not in c["symbol"]:
            continue

        coins.append({
            "symbol": c["symbol"],
            "change": float(c["priceChangePercent"]),
            "volume": float(c["quoteVolume"])
        })

    gainers = sorted(coins, key=lambda x: x["change"], reverse=True)[:15]
    losers = sorted(coins, key=lambda x: x["change"])[:15]

    return gainers + losers

# =========================
# KLINE
# =========================
def get_klines(symbol):
    r = requests.get(
        "https://fapi.binance.com/fapi/v1/klines",
        params={"symbol": symbol, "interval": "15m", "limit": 50}
    )

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

    # momentum
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
def smart_signal(d, daily_change):

    # DEVAM (trend devam)
    if daily_change > 5 and d["change_15m"] > 0 and d["vol"] > 1.3:
        return "LONG DEVAM 🚀"

    if daily_change < -5 and d["change_15m"] < 0 and d["vol"] > 1.3:
        return "SHORT DEVAM 📉"

    # DÖNÜŞ
    if daily_change > 8 and d["change_15m"] < 0:
        return "SHORT (DÖNÜŞ) ⚠️"

    if daily_change < -8 and d["change_15m"] > 0:
        return "LONG (DÖNÜŞ) ⚠️"

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
# MAIN
# =========================
def run():
    send("🚀 SMART BOT BAŞLADI")

    coins = get_top_movers()
    signals = []

    for c in coins:
        sym = c["symbol"]
        daily = c["change"]

        d = analyze(sym)
        if not d:
            continue

        signal = smart_signal(d, daily)
        if not signal:
            continue

        if abs(d["change_15m"]) < MIN_15M_CHANGE:
            continue

        if d["vol"] < MIN_VOL:
            continue

        tp, sl = levels(d["price"], signal)

        score = abs(daily) + abs(d["change_15m"]) + d["vol"]

        signals.append({
            "sym": sym,
            "signal": signal,
            "price": d["price"],
            "tp": tp,
            "sl": sl,
            "daily": daily,
            "m15": d["change_15m"],
            "vol": d["vol"],
            "score": score
        })

    # en güçlü 5 coin
    signals = sorted(signals, key=lambda x: x["score"], reverse=True)[:5]

    if not signals:
        send("❌ Sinyal yok")
        return

    for s in signals:
        msg = (
            f"🔥 AKILLI SİNYAL\n\n"
            f"{s['sym']}\n\n"
            f"{s['signal']}\n\n"
            f"Giriş: {s['price']:.4f}\n"
            f"🎯 TP: {s['tp']:.4f}\n"
            f"🛑 SL: {s['sl']:.4f}\n\n"
            f"24h: %{s['daily']:.2f}\n"
            f"15dk: %{s['m15']:.2f}\n"
            f"Hacim: x{s['vol']:.2f}\n\n"
            f"Saat: {datetime.now().strftime('%H:%M:%S')}"
        )

        send(msg)

    send("📊 Tarama tamamlandı")

if __name__ == "__main__":
    run()
