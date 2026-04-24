import os
import requests
import time

# 🔐 TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

DEBUG = True

# 📩 SEND
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

# 📊 BINANCE
def get_coins():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if not isinstance(data, list):
            return []

        return [c for c in data if c["symbol"].endswith("USDT")]
    except:
        return []

# 🧠 ANALYZE + DEBUG
def analyze():
    coins = get_coins()

    signals = []
    logs = []

    if not coins:
        return signals, ["API boş"]

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
                reasons.append("Trend +")
            else:
                logs.append(f"{name}: trend -")

            # 📦 volume
            if vol > 30_000_000:
                score += 2
            else:
                logs.append(f"{name}: düşük hacim")

            # 🚀 momentum
            if ch24 > 2:
                score += 1
            elif ch24 < -2:
                score += 1

            logs.append(f"{name} score={score}")

            # 🎯 SIGNAL
            if score >= 3:
                direction = "🚀 LONG" if ch24 > 0 else "🔻 SHORT"

                msg = f"""
<b>{name} {direction}</b>

💰 Fiyat: {price}
📊 Score: {score}

📈 24h: {round(ch24,2)}%
📦 Volume: {int(vol)}

🧠 Sinyal oluştu
"""
                signals.append(msg)

        except Exception as e:
            logs.append(f"HATA {str(e)}")

    return signals, logs

# 🧠 DEBUG SEND
def send_debug(logs):
    if not DEBUG:
        return

    msg = "🧠 DEBUG RAPORU\n\n"
    for l in logs[:20]:
        msg += f"- {l}\n"

    send(msg)

# 🚀 MAIN
def main():
    send("📡 SCALP BOT BAŞLADI")

    signals, logs = analyze()

    send_debug(logs)

    if not signals:
        send("❌ Sinyal yok")
        return

    for s in signals[:5]:
        send(s)
        time.sleep(1)

    send(f"📊 BİTTİ | Sinyal: {len(signals)}")

if __name__ == "__main__":
    main()
