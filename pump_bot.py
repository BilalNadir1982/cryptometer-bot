import requests
import time
from datetime import datetime

# TELEGRAM AYARLARI
TELEGRAM_TOKEN = "8701403795:AAFH5W28DmP1TVXRBCfZYn3wOiC8w8wEuAU"
CHAT_ID = "768262682"

# AYARLAR
MIN_VOLUME = 5000000   # minimum hacim (5M)
MIN_CHANGE = 3         # % değişim (ani hareket filtresi)
COOLDOWN = 3600       # aynı coin için 1 saat sessizlik

last_sent = {}

def send_telegram(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": CHAT_ID, "text": msg}
    requests.post(url, data=data)

def get_market_data():
    url = "https://api.coingecko.com/api/v3/coins/markets"
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 100,
        "page": 1,
        "price_change_percentage": "1h"
    }
    return requests.get(url, params=params).json()

def analyze():
    coins = get_market_data()

    for coin in coins:
        name = coin["symbol"].upper()
        price = coin["current_price"]
        change = coin.get("price_change_percentage_1h_in_currency", 0)
        volume = coin["total_volume"]

        if change is None:
            continue

        # 🔥 RAPID MOVEMENT FİLTRESİ
        if abs(change) > MIN_CHANGE and volume > MIN_VOLUME:

            now = time.time()
            if name in last_sent and now - last_sent[name] < COOLDOWN:
                continue

            last_sent[name] = now

            direction = "🚀 YÜKSELİŞ" if change > 0 else "📉 DÜŞÜŞ"

            strength = "ZAYIF"
            if abs(change) > 5:
                strength = "ORTA"
            if abs(change) > 8:
                strength = "GÜÇLÜ"

            msg = f"""
🔥 RAPID MOVEMENT TESPİT

Coin: {name}
Fiyat: ${price}

Değişim (1h): %{round(change,2)}
Hacim: ${volume}

Yön: {direction}
Güç: {strength}

Zaman: {datetime.now().strftime('%H:%M:%S')}
"""
            send_telegram(msg)

def run():
    print("Bot çalışıyor...")
    send_telegram("✅ Rapid Movement Bot Aktif")

    while True:
        try:
            analyze()
            time.sleep(300)  # 5 dk
        except Exception as e:
            print("Hata:", e)
            time.sleep(60)

if __name__ == "__main__":
    run()
