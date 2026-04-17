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
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    requests.post(url, data={"chat_id": CHAT_ID, "text": msg})

# =========================
# AYARLAR
# =========================
MIN_15M_CHANGE = 1.2
MIN_VOLUME_RATIO = 1.3
MAX_COINS = 25

COOLDOWN_MIN = 60  # aynı coin tekrar atmasın

# =========================
# COOLDOWN SİSTEMİ
# =========================
COOLDOWN_FILE = "cooldown.json"

def load_cooldown():
    try:
        with open(COOLDOWN_FILE, "r") as f:
            return json.load(f)
    except:
        return {}

def save_cooldown(data):
    with open(COOLDOWN_FILE, "w") as f:
        json.dump(data, f)

def is_on_cooldown(symbol, cooldown):
    if symbol not in cooldown:
        return False
    last_time = datetime.fromisoformat(cooldown[symbol])
    return datetime.now() - last_time < timedelta(minutes=COOLDOWN_MIN)

def update_cooldown(symbol, cooldown):
    cooldown[symbol] = datetime.now().isoformat()

# =========================
# COIN LİSTESİ
# =========================
def get_top_coins():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {"vs_currency": "usd", "order": "volume_desc", "per_page": 100}
    data = requests.get(url, params=params).json()

    coins = []
    for c in data:
        sym = c["symbol"].upper()
        if sym not in ["USDT", "USDC", "BUSD"]:
            coins.append(sym)

    return coins[:MAX_COINS]

# =========================
# KLINE
# =========================
def get_klines(symbol):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": f"{symbol}USDT", "interval": "15m", "limit": 50}

    r = requests.get(url, params=params)
    if r.status_code != 200:
        return None

    df = pd.DataFrame(r.json())
    df = df[[4, 5]]
    df.columns = ["close", "volume"]
    df = df.astype(float)
    return df

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
    vol_ratio = last["volume"] / vol_avg if vol_avg > 0 else 0

    # momentum
    up_trend = df["close"].iloc[-1] > df["close"].iloc[-3]

    return {
        "price": last["close"],
        "change": change_15m,
        "vol_ratio": vol_ratio,
        "trend": up_trend
    }

# =========================
# SİNYAL
# =========================
def check_signal(data):
    if abs(data["change"]) < MIN_15M_CHANGE:
        return None

    if data["vol_ratio"] < MIN_VOLUME_RATIO:
        return None

    if not data["trend"]:
        return None

    strength = "ORTA"
    if abs(data["change"]) > 2.5:
        strength = "GUCLU"

    return strength

# =========================
# MAIN
# =========================
def run():
    send("🚀 Pump bot çalıştı...")

    coins = get_top_coins()
    cooldown = load_cooldown()

    sent = 0

    for coin in coins:
        if is_on_cooldown(coin, cooldown):
            continue

        data = analyze(coin)
        if not data:
            continue

        strength = check_signal(data)

        if strength:
            msg = (
                f"🔥 PUMP SİNYALİ\n\n"
                f"Coin: {coin}\n"
                f"Fiyat: {data['price']:.6f}\n"
                f"15 DK: %{data['change']:.2f}\n"
                f"Hacim: x{data['vol_ratio']:.2f}\n"
                f"Güç: {strength}\n"
                f"Saat: {datetime.now().strftime('%H:%M:%S')}"
            )

            send(msg)
            update_cooldown(coin, cooldown)
            sent += 1

    save_cooldown(cooldown)

    send(f"📊 Tarama bitti\nSinyal: {sent}")

if __name__ == "__main__":
    run()
