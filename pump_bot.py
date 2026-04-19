import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

FUTURES_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FUTURES_TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"
FUTURES_OPEN_INTEREST_URL = "https://fapi.binance.com/fapi/v1/openInterest"
FUTURES_MARK_PRICE_URL = "https://fapi.binance.com/fapi/v1/premiumIndex"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})


def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    r = requests.post(url, data=data, timeout=20)
    print("Telegram:", r.status_code, r.text[:200])


def get_json(url, params=None):
    try:
        r = SESSION.get(url, params=params, timeout=20)
        data = r.json()

        if isinstance(data, dict) and data.get("code") not in (None, 0):
            print("API hata:", data)
            return None

        return data
    except Exception as e:
        print("İstek hatası:", e)
        return None


def get_futures_symbols():
    data = get_json(FUTURES_EXCHANGE_INFO_URL)
    if not data or "symbols" not in data:
        return []

    symbols = []
    for item in data["symbols"]:
        symbol = item.get("symbol", "")
        contract_type = item.get("contractType", "")
        quote_asset = item.get("quoteAsset", "")
        status = item.get("status", "")

        if quote_asset != "USDT":
            continue
        if status != "TRADING":
            continue
        if contract_type not in ("PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"):
            continue

        symbols.append(symbol)

    return symbols


def get_futures_tickers():
    data = get_json(FUTURES_TICKER_24H_URL)
    if not isinstance(data, list):
        return []

    return data


def build_coin_map():
    valid_symbols = set(get_futures_symbols())
    tickers = get_futures_tickers()

    if not valid_symbols or not tickers:
        return []

    coins = []

    for c in tickers:
        symbol = c.get("symbol", "")
        if symbol not in valid_symbols:
            continue

        try:
            change_pct = float(c.get("priceChangePercent", 0))
            quote_volume = float(c.get("quoteVolume", 0))
            last_price = float(c.get("lastPrice", 0))
            volume = float(c.get("volume", 0))
        except Exception:
            continue

        if quote_volume <= 0 or last_price <= 0:
            continue

        coins.append({
            "symbol": symbol,
            "change_pct": change_pct,
            "quote_volume": quote_volume,
            "last_price": last_price,
            "volume": volume
        })

    return coins


def get_open_interest(symbol):
    data = get_json(FUTURES_OPEN_INTEREST_URL, {"symbol": symbol})
    if not data:
        return 0.0
    try:
        return float(data.get("openInterest", 0))
    except Exception:
        return 0.0


def get_mark_price_data(symbol):
    data = get_json(FUTURES_MARK_PRICE_URL, {"symbol": symbol})
    if not data:
        return {"markPrice": 0.0, "lastFundingRate": 0.0}

    try:
        return {
            "markPrice": float(data.get("markPrice", 0)),
            "lastFundingRate": float(data.get("lastFundingRate", 0))
        }
    except Exception:
        return {"markPrice": 0.0, "lastFundingRate": 0.0}


def top_gainers(coins, limit=10):
    return sorted(coins, key=lambda x: x["change_pct"], reverse=True)[:limit]


def top_losers(coins, limit=10):
    return sorted(coins, key=lambda x: x["change_pct"])[:limit]


def top_volume(coins, limit=10):
    return sorted(coins, key=lambda x: x["quote_volume"], reverse=True)[:limit]


def top_hot_money(coins, limit=10):
    enriched = []

    # Fazla istek atmamak için sadece hacmi yüksek coinlerden seçiyoruz
    base_candidates = sorted(coins, key=lambda x: x["quote_volume"], reverse=True)[:25]

    for c in base_candidates:
        oi = get_open_interest(c["symbol"])
        mp = get_mark_price_data(c["symbol"])
        funding = abs(mp["lastFundingRate"])

        # sıcak para skoru = hacim + hareket + open interest + funding etkisi
        score = (
            (c["quote_volume"] / 1_000_000)
            + abs(c["change_pct"]) * 2
            + (oi / 100_000)
            + funding * 10000
        )

        item = c.copy()
        item["open_interest"] = oi
        item["funding_rate"] = mp["lastFundingRate"]
        item["hot_score"] = score
        enriched.append(item)

    return sorted(enriched, key=lambda x: x["hot_score"], reverse=True)[:limit]


def format_simple_list(title, items, mode):
    lines = [title]

    for i, c in enumerate(items, start=1):
        if mode == "move":
            lines.append(
                f"{i}. {c['symbol']} | %{c['change_pct']:.2f} | Hacim: {c['quote_volume']:,.0f}"
            )
        elif mode == "volume":
            lines.append(
                f"{i}. {c['symbol']} | Hacim: {c['quote_volume']:,.0f} | %{c['change_pct']:.2f}"
            )
        elif mode == "hot":
            lines.append(
                f"{i}. {c['symbol']} | Skor: {c['hot_score']:.2f} | %{c['change_pct']:.2f} | OI: {c['open_interest']:,.0f}"
            )

    return "\n".join(lines)


def main():
    print("Futures bot çalıştı")

    coins = build_coin_map()

    if not coins:
        send_telegram("❌ Binance Futures verisi alınamadı")
        return

    gainers = top_gainers(coins, 10)
    losers = top_losers(coins, 10)
    volumes = top_volume(coins, 10)
    hot_money = top_hot_money(coins, 10)

    msg = (
        "📊 BINANCE FUTURES RAPORU\n\n"
        + format_simple_list("🚀 EN ÇOK YÜKSELENLER", gainers, "move")
        + "\n\n"
        + format_simple_list("🔻 EN ÇOK DÜŞENLER", losers, "move")
        + "\n\n"
        + format_simple_list("💰 EN YÜKSEK HACİM", volumes, "volume")
        + "\n\n"
        + format_simple_list("🔥 SICAK PARA", hot_money, "hot")
    )

    # Telegram mesaj limiti için böl
    max_len = 3500
    parts = [msg[i:i + max_len] for i in range(0, len(msg), max_len)]

    for part in parts:
        send_telegram(part)


if __name__ == "__main__":
    main()
