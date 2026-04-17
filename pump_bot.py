import os
import requests
from datetime import datetime

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
CRYPTOMETER_API_KEY = os.getenv("CRYPTOMETER_API_KEY")

def send(msg: str):
    if not TOKEN or not CHAT_ID:
        print("Telegram ayarlari eksik")
        return
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            data={"chat_id": CHAT_ID, "text": msg},
            timeout=20
        )
        print("Telegram:", r.status_code, r.text[:200])
    except Exception as e:
        print("Telegram hata:", e)

def cm_get(path: str, params: dict):
    base = "https://api.cryptometer.io"
    all_params = dict(params)
    all_params["api_key"] = CRYPTOMETER_API_KEY
    r = requests.get(f"{base}{path}", params=all_params, timeout=30)
    print("CM:", path, r.status_code)
    if r.status_code != 200:
        return None
    try:
        data = r.json()
    except Exception:
        return None
    if str(data.get("success")).lower() != "true":
        return None
    return data.get("data")

def get_binance_futures_large_activity():
    return cm_get("/large-trades-activity/", {"e": "binance_futures"}) or []

def get_whale_trades(symbol: str):
    # docs örneğinde symbol btc gibi geçiyor
    return cm_get("/xtrades/", {"e": "binance_futures", "symbol": symbol.lower()}) or []

def get_rapid_movements():
    return cm_get("/rapid-movements/", {}) or []

def get_open_interest(symbol: str):
    # pair formatı dokümanda market_pair ile geçiyor; borsaya göre değişebilir
    pair = symbol.lower()
    data = cm_get("/open-interest/", {"e": "binance_futures", "market_pair": pair})
    return data or []

def summarize_whales(rows):
    buy_total = 0.0
    sell_total = 0.0

    for x in rows:
        side = str(x.get("side", "")).upper()
        total = float(x.get("total") or 0)
        if side == "BUY":
            buy_total += total
        elif side == "SELL":
            sell_total += total

    net = buy_total - sell_total
    return buy_total, sell_total, net

def pick_candidates():
    candidates = {}

    activity = get_binance_futures_large_activity()
    for row in activity:
        pair = str(row.get("pair", "")).upper().replace("-", "")
        if pair.endswith("USDT"):
            candidates[pair] = {"source": "large_activity"}

    rapid = get_rapid_movements()
    for row in rapid:
        pair = str(row.get("pair", "")).upper().replace("-", "")
        exch = str(row.get("exchange", "")).lower()
        if pair.endswith("USDT") and "binance" in exch:
            candidates[pair] = {"source": "rapid"}

    return list(candidates.keys())[:10]

def classify_signal(symbol: str):
    base_symbol = symbol.replace("USDT", "")
    whale_rows = get_whale_trades(base_symbol)
    if not whale_rows:
        return None, "whale_veri_yok"

    buy_total, sell_total, net = summarize_whales(whale_rows)

    oi_rows = get_open_interest(base_symbol)
    oi_value = None
    if oi_rows and isinstance(oi_rows, list) and len(oi_rows) > 0:
        try:
            oi_value = float(oi_rows[0].get("open_interest"))
        except Exception:
            oi_value = None

    if buy_total > sell_total * 1.35 and net > 250000:
        return {
            "signal": "LONG WHALE",
            "buy_total": buy_total,
            "sell_total": sell_total,
            "net": net,
            "oi": oi_value,
        }, None

    if sell_total > buy_total * 1.35 and net < -250000:
        return {
            "signal": "SHORT WHALE",
            "buy_total": buy_total,
            "sell_total": sell_total,
            "net": net,
            "oi": oi_value,
        }, None

    return None, "denge_var"

def run():
    send("🐋 CryptoMeter Whale Bot çalıştı")

    if not CRYPTOMETER_API_KEY:
        send("❌ CRYPTOMETER_API_KEY eksik")
        return

    candidates = pick_candidates()
    if not candidates:
        send("❌ Aday coin bulunamadı")
        return

    found = 0
    reject = {}

    for symbol in candidates:
        result, reason = classify_signal(symbol)
        if not result:
            reject[reason] = reject.get(reason, 0) + 1
            print(symbol, "elendi:", reason)
            continue

        msg = (
            f"🐋 BALİNA SİNYALİ\n\n"
            f"Coin: {symbol}\n"
            f"Tür: {result['signal']}\n"
            f"Whale Buy: ${result['buy_total']:,.0f}\n"
            f"Whale Sell: ${result['sell_total']:,.0f}\n"
            f"Net: ${result['net']:,.0f}\n"
            f"Open Interest: {result['oi'] if result['oi'] is not None else 'yok'}\n"
            f"Saat: {datetime.now().strftime('%H:%M:%S')}"
        )
        send(msg)
        found += 1

    if found == 0:
        send(f"❌ Sinyal yok | Eleme: {reject}")

    send(f"📊 Tarama bitti | Sinyal: {found}")

if __name__ == "__main__":
    run()
