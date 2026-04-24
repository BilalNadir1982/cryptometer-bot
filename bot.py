import os
import requests
import time

# 🔐 TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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
    r = requests.get(url, timeout=10)
    data = r.json()

    if not isinstance(data, list):
        return []

    return [c for c in data if c["symbol"].endswith("USDT")]

# 🧠 TREND SCORE (TV MANTIK)
def analyze():
    coins = get_coins()
    signals = []

    coins = sorted(coins, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]

    for c in coins:
        try:
            name = c["symbol"]
            price = float(c["lastPrice"])
            ch24 = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])

            # =========================
            # 🧠 TRADINGVIEW MANTIĞI
            # =========================

            score = 0
            reasons = []

            # EMA proxy (trend)
            if ch24 > 0:
                score += 1
                reasons.append("Pozitif trend")

            if ch24 > 3:
                score += 1
                reasons.append("Güçlü yükseliş")

            if ch24 < -3:
                score += 1
                reasons.append("Güçlü düşüş")

            # RSI proxy
            if abs(ch24) < 1:
                score -= 1
                reasons.append("Zayıf momentum")

            # MACD proxy
            if ch24 > 1:
                score += 1

            # Volume spike
            if vol > 30_000_000:
                score += 2
                reasons.append("Volume spike")

            # Whale
            if vol > 80_000_000:
                score += 1
                reasons.append("Whale hareketi")

            # =========================
            # 🎯 SIGNAL
            # =========================

            if score >= 3:
                direction = "🚀 LONG" if ch24 > 0 else "🔻 SHORT"

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
    send("📡 TV STRATEJİ BOT BAŞLADI")

    signals = analyze()

    if not signals:
        return  # sessiz mod

    for s in signals[:5]:
        send(s)
        time.sleep(1)

    send(f"📊 BİTTİ | Sinyal: {len(signals)}")

if __name__ == "__main__":
    main()
