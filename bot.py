import os
import requests
import time

# 🔐 TELEGRAM
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

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

# 📊 BINANCE FUTURES
def get_coins():
    url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not isinstance(data, list):
        print("API ERROR:", data)
        return []

    return [c for c in data if "symbol" in c and c["symbol"].endswith("USDT")]

# 💰 FUNDING
def get_funding():
    url = "https://fapi.binance.com/fapi/v1/premiumIndex"
    r = requests.get(url, timeout=10)
    data = r.json()

    if not isinstance(data, list):
        return []

    return data

# 📦 OPEN INTEREST
def get_oi(symbol):
    try:
        url = f"https://fapi.binance.com/fapi/v1/openInterest?symbol={symbol}"
        r = requests.get(url, timeout=10)
        return float(r.json()["openInterest"])
    except:
        return 0

# 🐋 WHALE DETECTION
def detect_whale(vol, avg=50000000):
    return vol > avg * 2.5

# 💣 LIQUIDATION (proxy)
def liquidation_signal(ch24, ch1, whale):
    if whale and abs(ch24) > 5:
        return "⚠️ OLASI LIQUIDATION"
    if ch24 > 8:
        return "SHORT LIQUIDATION RİSKİ"
    if ch24 < -8:
        return "LONG LIQUIDATION RİSKİ"
    return None

# ⚡ SCALP
def scalp_signal(ch1, vol):
    if ch1 > 0.8 and vol > 20000000:
        return "🚀 LONG SCALP"
    if ch1 < -0.8 and vol > 20000000:
        return "🔻 SHORT SCALP"
    return None

# 🤖 AI SCORE
def ai_score(ch1, ch24, vol, fund, oi):
    score = 0

    if abs(ch24) > 3:
    score += 1

    if vol > 30_000_000:
        score += 2

    if fund > 0.01:
        score += 2
    elif fund < -0.01:
        score += 2

    if oi > 100000:
        score += 2

    if abs(ch1) > 1:
        score += 2

    return score

# 🔥 TOP MOVERS
def get_top_movers(coins):
    for c in coins:
        c["change"] = float(c["priceChangePercent"])

    gainers = sorted(coins, key=lambda x: x["change"], reverse=True)[:5]
    losers = sorted(coins, key=lambda x: x["change"])[:5]

    return gainers, losers

def format_movers(gainers, losers):
    msg = "🔥 <b>TOP GAINERS</b>\n\n"

    for g in gainers:
        msg += f"{g['symbol']} → {round(g['change'],2)}%\n"

    msg += "\n🔻 <b>TOP LOSERS</b>\n\n"

    for l in losers:
        msg += f"{l['symbol']} → {round(l['change'],2)}%\n"

    return msg

# 🧠 ANALYZE
def analyze():
    coins = get_coins()
    signals = []

    funding = get_funding()
    fund_map = {x["symbol"]: float(x["lastFundingRate"]) for x in funding}

    if not coins:
        return signals

    coins = sorted(coins, key=lambda x: float(x["quoteVolume"]), reverse=True)[:100]

    for c in coins:
        try:
            name = c["symbol"]
            price = float(c["lastPrice"])
            vol = float(c["quoteVolume"])
            ch24 = float(c["priceChangePercent"])
            trades = int(c["count"])

            fund = fund_map.get(name, 0)
            oi = get_oi(name)

            ch1 = ch24 / 24  # Binance 1h yok → approx

            whale = detect_whale(vol)
            liq = liquidation_signal(ch24, ch1, whale)
            scalp = scalp_signal(ch1, vol)

            score = ai_score(ch1, ch24, vol, fund, oi)

            reasons = []

            if whale:
                reasons.append("🐋 Whale hareketi")

            if liq:
                reasons.append(liq)

            if scalp:
                reasons.append(scalp)

            if score >= 4:
                direction = "🚀 LONG" if ch24 > 0 else "🔻 SHORT"

                msg = f"""
<b>{name} {direction}</b>

💰 Fiyat: {price}
📊 Score: {score}/10

📈 24h: {round(ch24,2)}%
💸 Funding: {fund}
📦 OI: {oi}
🔄 Trades: {trades}

🧠 Sinyaller:
- {chr(10).join(reasons)}
"""
                signals.append(msg)

        except:
            continue

    return signals

# 🚀 MAIN
def main():
    send("🤖 PRO BOT ÇALIŞTI - TARAMA BAŞLADI")

    coins = get_coins()
    gainers, losers = get_top_movers(coins)

    if gainers and losers:
        send(format_movers(gainers, losers))

    signals = analyze()

    if not signals:
        send("❌ Sinyal yok")
    else:
        for s in signals[:5]:
            send(s)
            time.sleep(1)

    send(f"📊 TARAMA BİTTİ | Sinyal: {len(signals)}")

if __name__ == "__main__":
    main()
