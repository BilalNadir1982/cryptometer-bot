import os
import requests
import time

# 🔐 TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# 📩 TELEGRAM GÖNDER
def send(msg):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, json={
        "chat_id": CHAT_ID,
        "text": msg,
        "parse_mode": "HTML"
    })

# 📊 BINANCE FUTURES DATA
def get_coins():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url)
    data = r.json()

    # sadece USDT pariteleri
    coins = [c for c in data if c["symbol"].endswith("USDT")]

    return coins

# 🔥 TOP GAINERS / LOSERS
def get_top_movers():
    coins = get_coins()

    for c in coins:
        c["change"] = float(c["priceChangePercent"])

    gainers = sorted(coins, key=lambda x: x["change"], reverse=True)[:5]
    losers = sorted(coins, key=lambda x: x["change"])[:5]

    return gainers, losers

# 🧾 FORMAT
def format_movers(gainers, losers):
    msg = "🔥 <b>TOP GAINERS</b>\n\n"

    for g in gainers:
        msg += f"{g['symbol']} → {round(float(g['change']),2)}%\n"

    msg += "\n🔻 <b>TOP LOSERS</b>\n\n"

    for l in losers:
        msg += f"{l['symbol']} → {round(float(l['change']),2)}%\n"

    return msg

# 🧠 SİNYAL ANALİZ
def analyze():
    coins = get_coins()
    signals = []

    # 🔥 sadece güçlü coinler
    coins = sorted(coins, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]

    for c in coins:
        name = c["symbol"]
        price = float(c["lastPrice"])
        vol = float(c["quoteVolume"])
        ch24 = float(c["priceChangePercent"])
        trades = int(c["count"])

        # küçük coin filtre
        if price < 0.0001:
            continue

        score = 0
        reasons = []

        # HACİM
        if vol > 50_000_000:
            score += 2
            reasons.append("Yüksek hacim")

        # YÜKSELİŞ
        if ch24 > 5:
            score += 2
            reasons.append("Güçlü yükseliş")

        # DÜŞÜŞ
        if ch24 < -5:
            score += 2
            reasons.append("Güçlü düşüş")

        # TRADE YOĞUNLUĞU
        if trades > 100000:
            score += 1
            reasons.append("Yoğun işlem")

        # WHALE
        if vol > 100_000_000 and abs(ch24) > 5:
            score += 3
            reasons.append("WHALE hareketi")

        if score >= 4:
            direction = "🚀 LONG" if ch24 > 0 else "🔻 SHORT"
            nedenler = "\n- ".join(reasons)

            msg = f"""
<b>{name} {direction}</b>

Fiyat: {price}
Skor: {score}/10

24h: {round(ch24,2)}%
Hacim: {int(vol)}

Neden:
- {nedenler}
"""
            signals.append(msg)

    return signals

# 🚀 MAIN
def main():
    send("🤖 Bot çalıştı - Tarama başlıyor...")

    # 🔥 GAINERS / LOSERS
    gainers, losers = get_top_movers()
    send(format_movers(gainers, losers))

    # 🧠 SİNYAL
    signals = analyze()

    if not signals:
        send("❌ Sinyal yok")
    else:
        for s in signals[:5]:
            send(s)
            time.sleep(1)

    send(f"📊 Tarama bitti | Sinyal: {len(signals)}")

# ▶️ ÇALIŞTIR
if __name__ == "__main__":
    main()
