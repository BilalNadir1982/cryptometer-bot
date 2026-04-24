import os
import requests
import time

# 🔐 TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 📩 TELEGRAM MESAJ
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

# 📊 BINANCE FUTURES VERİ
def get_coins():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"

    try:
        r = requests.get(url, timeout=10)
        data = r.json()

        if not isinstance(data, list):
            print("API HATA:", data)
            return []

        return [c for c in data if c["symbol"].endswith("USDT")]

    except Exception as e:
        print("API error:", e)
        return []

# ⚡ SCALP ANALİZ
def analyze():
    coins = get_coins()
    signals = []

    if not coins:
        return signals

    coins = sorted(coins, key=lambda x: float(x["quoteVolume"]), reverse=True)[:150]

    for c in coins:
        try:
            name = c["symbol"]
            price = float(c["lastPrice"])
            vol = float(c["quoteVolume"])
            ch24 = float(c["priceChangePercent"])

            momentum = ch24 / 24

            score = 0
            reasons = []

            if abs(momentum) > 0.3:
                score += 2
                reasons.append("Momentum")

            if vol > 30_000_000:
                score += 2
                reasons.append("Hacim yüksek")

            if ch24 > 2:
                score += 1
                reasons.append("Pump")

            if ch24 < -2:
                score += 1
                reasons.append("Dump")

            if vol > 80_000_000:
                score += 2
                reasons.append("Whale hareketi")

            if score >= 3:
                direction = "🚀 LONG SCALP" if ch24 > 0 else "🔻 SHORT SCALP"

                msg = f"""
<b>{name} {direction}</b>

💰 Fiyat: {price}
📊 Score: {score}/6

📈 24h: {round(ch24,2)}%
📦 Hacim: {int(vol)}

🧠 Neden:
- {chr(10).join(reasons)}
"""
                signals.append(msg)

        except:
            continue

    return signals

# 🚀 MAIN
def main():
    send("⚡ SCALP BOT BAŞLADI")

    signals = analyze()

    if not signals:
        return  # ❌ sessiz mod (spam yok)

    for s in signals[:5]:
        send(s)
        time.sleep(1)

    send(f"📊 TARAMA BİTTİ | Sinyal: {len(signals)}")

# ▶️ ÇALIŞTIR
if __name__ == "__main__":
    main()
