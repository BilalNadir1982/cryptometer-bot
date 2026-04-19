import os
import requests
from datetime import datetime

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

BINANCE_URL = "https://api.binance.com/api/v3/ticker/24hr"

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    requests.post(url, data=data, timeout=20)

def get_market_data():
    r = requests.get(BINANCE_URL)
    return r.json()

def filter_coins(data):
    coins = []

    for c in data:
        symbol = c["symbol"]

        if not symbol.endswith("USDT"):
            continue

        volume = float(c["quoteVolume"])
        change = float(c["priceChangePercent"])

        if volume < 500000:  # düşük hacim ele
            continue

        coins.append({
            "symbol": symbol,
            "change": change,
            "volume": volume
        })

    return coins

def find_signals(coins):
    signals = []

    for c in coins:
        if c["change"] >= 5:
            signals.append(f"🚀 YÜKSELEN\n{c['symbol']} % {c['change']:.2f}")

        elif c["change"] <= -5:
            signals.append(f"🔻 DÜŞEN\n{c['symbol']} % {c['change']:.2f}")

    return signals

def main():
    print("Bot çalıştı - tarama başlıyor")

    data = get_market_data()
    coins = filter_coins(data)
    signals = find_signals(coins)

    if signals:
        for s in signals[:10]:
            send_telegram(s)
    else:
        send_telegram("ℹ️ Sinyal bulunamadı")

if __name__ == "__main__":
    main()
