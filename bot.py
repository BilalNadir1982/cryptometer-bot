import os
import requests
import time

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
API_KEY = os.getenv("COINGECKO_API_KEY")

headers = {
    "x-cg-demo-api-key": API_KEY
}

def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

def get_coins():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 50,
        "page": 1,
        "price_change_percentage": "1h,24h"
    }

    r = requests.get(url, params=params, headers=headers)
    return r.json()

def analyze():
    coins = get_coins()

    signals = []

    for c in coins:
        name = c["symbol"].upper()
        price = c["current_price"]
        vol = c["total_volume"]
        ch1 = c.get("price_change_percentage_1h_in_currency", 0)
        ch24 = c.get("price_change_percentage_24h", 0)

        score = 0
        reasons = []

        # HACİM
        if vol > 10_000_000:
            score += 1
            reasons.append("Yüksek hacim")

        # 1H PUMP
        if ch1 > 2:
            score += 2
            reasons.append("1h pump")

        # 1H DUMP
        if ch1 < -2:
            score += 2
            reasons.append("1h dump")

        # 24H GÜÇ
        if abs(ch24) > 5:
            score += 1
            reasons.append("24h güçlü hareket")

        # PSEUDO WHALE
        if vol > 50_000_000 and abs(ch1) > 2:
            score += 3
            reasons.append("WHALE hareketi")

        if score >= 4:
            direction = "🚀 LONG" if ch1 > 0 else "🔻 SHORT"

            nedenler = "\n- ".join(reasons)

msg = f"""
<b>{name} {direction}</b>

Fiyat: {price}
Skor: {score}/10

1h: {round(ch1,2)}%
24h: {round(ch24,2)}%

Neden:
- {nedenler}
"""
            signals.append(msg)

    return signals

def main():
    send("🤖 Bot çalıştı - Tarama başlıyor...")

    signals = analyze()

    if not signals:
        send("❌ Sinyal yok")
    else:
        for s in signals[:5]:
            send(s)
            time.sleep(1)

    send(f"📊 Tarama bitti | Sinyal: {len(signals)}")

if __name__ == "__main__":
    main()
