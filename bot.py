import os
import requests
import time

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DEBUG = True

# 📩 TELEGRAM
def send(msg):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": msg,
            "parse_mode": "HTML"
        }, timeout=10)
    except:
        print("Telegram error")

# 🔵 BINANCE FUTURES
def get_binance():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if isinstance(data, dict):
            return []

        return data
    except:
        return []

# 🟢 COINGECKO FALLBACK
def get_coingecko():
    url = "https://api.coingecko.com/api/v3/coins/markets"

    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 50,
        "page": 1,
        "price_change_percentage": "24h"
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        data = r.json()

        coins = []
        for c in data:
            coins.append({
                "symbol": c["symbol"].upper() + "USDT",
                "lastPrice": c["current_price"],
                "quoteVolume": c["total_volume"],
                "priceChangePercent": c.get("price_change_percentage_24h", 0)
            })

        return coins
    except:
        return []

# 🔥 UNIFIED DATA
def get_coins():
    data = get_binance()

    if not data:
        if DEBUG:
            print("Binance yok → CoinGecko aktif")
        data = get_coingecko()

    return data

# 🧠 ANALYZE
def analyze():
    coins = get_coins()

    signals = []
    logs = []

    if not coins:
        return signals, ["API FULL FAIL"]

    coins = sorted(coins, key=lambda x: float(x["quoteVolume"]), reverse=True)[:50]

    for c in coins:
        try:
            name = c["symbol"]
            price = float(c["lastPrice"])
            ch24 = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])

            score = 0
            reasons = []

            # 📈 trend
            if ch24 > 0:
                score += 1
            else:
                logs.append(f"{name} trend -")

            # 📦 volume
            if vol > 30_000_000:
                score += 2
            else:
                logs.append(f"{name} low volume")

            # 🚀 momentum
            if ch24 > 2:
                score += 1
                reasons.append("Pump")
            elif ch24 < -2:
                score += 1
                reasons.append("Dump")

            logs.append(f"{name} score={score}")

            # 🎯 SIGNAL
            if score >= 3:
                direction = "🚀 LONG" if ch24 > 0 else "🔻 SHORT"

                msg = f"""
<b>{name} {direction}</b>

💰 Price: {price}
📊 Score: {score}

📈 24h: {round(ch24,2)}%
📦 Volume: {int(vol)}

🧠 {', '.join(reasons)}
"""
                signals.append(msg)

        except:
            continue

    return signals, logs

# 🧠 DEBUG
def send_debug(logs):
    if not DEBUG:
        return

    msg = "🧠 DEBUG RAPORU\n\n"
    for l in logs[:20]:
        msg += f"- {l}\n"

    send(msg)

# 🚀 MAIN
def main():
    send("📡 SCALP BOT STARTED (DUAL API)")

    signals, logs = analyze()

    send_debug(logs)

    if not signals:
        send("❌ Sinyal yok")
        return

    for s in signals[:5]:
        send(s)
        time.sleep(1)

    send(f"📊 DONE | Signals: {len(signals)}")

if __name__ == "__main__":
    main()
