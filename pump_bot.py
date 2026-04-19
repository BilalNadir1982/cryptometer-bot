import os
import time
import requests
from datetime import datetime

# =========================
# AYARLAR
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

SPOT_BASE_URL = "https://data-api.binance.vision"
ALPHA_BASE_URL = "https://www.binance.com"

REQUEST_TIMEOUT = 20

# Daha agresif ayarlar
SPOT_INTERVAL = "5m"
SPOT_KLINE_LIMIT = 120
SPOT_TOP_SYMBOLS_LIMIT = 60
SPOT_MIN_QUOTE_VOLUME_USDT = 3_000_000
SPOT_SIGNAL_THRESHOLD = 4

ALPHA_INTERVAL = "5m"
ALPHA_KLINE_LIMIT = 120
ALPHA_SIGNAL_THRESHOLD = 4
ALPHA_MAX_SYMBOLS = 80

MAX_SEND_PER_GROUP = 5


# =========================
# YARDIMCI
# =========================

def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram ayarları eksik.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        log(f"Telegram status: {r.status_code}")
        if r.status_code != 200:
            log(f"Telegram response: {r.text}")
    except Exception as e:
        log(f"Telegram gönderme hatası: {e}")


def get_json(url: str, params=None):
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def alpha_get_json(path: str, params=None):
    url = f"{ALPHA_BASE_URL}{path}"
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    data = r.json()

    if not isinstance(data, dict):
        raise Exception(f"Alpha API beklenmeyen cevap: {data}")

    if not data.get("success", False):
        raise Exception(f"Alpha API hata: {data}")

    return data.get("data")


def pct_change(a: float, b: float) -> float:
    if a == 0:
        return 0.0
    return ((b - a) / a) * 100.0


def ema(values, period):
    if len(values) < period:
        return None

    multiplier = 2 / (period + 1)
    ema_value = sum(values[:period]) / period

    for v in values[period:]:
        ema_value = (v - ema_value) * multiplier + ema_value

    return ema_value


def rsi(closes, period=14):
    if len(closes) < period + 1:
        return None

    gains = []
    losses = []

    for i in range(1, period + 1):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(abs(min(diff, 0)))

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

    for i in range(period + 1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gain = max(diff, 0)
        loss = abs(min(diff, 0))

        avg_gain = ((avg_gain * (period - 1)) + gain) / period
        avg_loss = ((avg_loss * (period - 1)) + loss) / period

    if avg_loss == 0:
        return 100.0

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


# =========================
# SPOT
# =========================

def get_spot_top_symbols():
    data = get_json(f"{SPOT_BASE_URL}/api/v3/ticker/24hr")
    symbols = []

    for item in data:
        symbol = item.get("symbol", "")

        if not symbol.endswith("USDT"):
            continue

        banned_parts = ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]
        if any(bp in symbol for bp in banned_parts):
            continue

        try:
            quote_volume = float(item.get("quoteVolume", 0))
            last_price = float(item.get("lastPrice", 0))
            price_change_percent = float(item.get("priceChangePercent", 0))
        except Exception:
            continue

        if quote_volume < SPOT_MIN_QUOTE_VOLUME_USDT:
            continue
        if last_price <= 0:
            continue

        symbols.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "price_change_percent_24h": price_change_percent
        })

    symbols.sort(key=lambda x: x["quote_volume"], reverse=True)
    return symbols[:SPOT_TOP_SYMBOLS_LIMIT]


def get_spot_klines(symbol: str, interval="5m", limit=120):
    data = get_json(
        f"{SPOT_BASE_URL}/api/v3/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit}
    )

    candles = []
    for k in data:
        candles.append({
            "open_time": int(k[0]),
            "open": float(k[1]),
            "high": float(k[2]),
            "low": float(k[3]),
            "close": float(k[4]),
            "volume": float(k[5]),
            "close_time": int(k[6]),
            "quote_volume": float(k[7]),
            "trade_count": int(k[8]),
        })
    return candles


def analyze_spot_symbol(symbol_data):
    symbol = symbol_data["symbol"]
    candles = get_spot_klines(symbol, SPOT_INTERVAL, SPOT_KLINE_LIMIT)

    if len(candles) < 60:
        return None

    closes = [c["close"] for c in candles]
    volumes = [c["quote_volume"] for c in candles]

    last_close = closes[-1]
    prev_close = closes[-2]
    close_5 = closes[-6] if len(closes) >= 6 else closes[0]
    close_15 = closes[-16] if len(closes) >= 16 else closes[0]

    rsi_val = rsi(closes, 14)
    ema_20 = ema(closes, 20)
    ema_50 = ema(closes, 50)

    last_vol = volumes[-1]
    avg_vol_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes[:-1]) / max(len(volumes) - 1, 1)

    move_1 = pct_change(prev_close, last_close)
    move_5 = pct_change(close_5, last_close)
    move_15 = pct_change(close_15, last_close)
    volume_ratio = (last_vol / avg_vol_20) if avg_vol_20 > 0 else 0

    bull_score = 0
    bear_score = 0
    reasons = []
    trend = "NÖTR"

    if ema_20 and ema_50:
        if ema_20 > ema_50:
            trend = "YUKARI"
            bull_score += 1
            reasons.append("EMA20>EMA50")
        else:
            trend = "AŞAĞI"
            bear_score += 1
            reasons.append("EMA20<EMA50")

    if move_1 >= 0.5:
        bull_score += 1
        reasons.append(f"1 mum %+{move_1:.2f}")
    elif move_1 <= -0.5:
        bear_score += 1
        reasons.append(f"1 mum %{move_1:.2f}")

    if move_5 >= 1.2:
        bull_score += 2
        reasons.append(f"5 mum %+{move_5:.2f}")
    elif move_5 <= -1.2:
        bear_score += 2
        reasons.append(f"5 mum %{move_5:.2f}")

    if move_15 >= 2.0:
        bull_score += 2
        reasons.append(f"15 mum %+{move_15:.2f}")
    elif move_15 <= -2.0:
        bear_score += 2
        reasons.append(f"15 mum %{move_15:.2f}")

    if volume_ratio >= 1.4:
        if move_1 >= 0:
            bull_score += 2
            reasons.append(f"Alım hacmi x{volume_ratio:.2f}")
        else:
            bear_score += 2
            reasons.append(f"Satış hacmi x{volume_ratio:.2f}")

    if rsi_val is not None:
        if 48 <= rsi_val <= 70:
            bull_score += 1
            reasons.append(f"RSI uygun {rsi_val:.1f}")
        elif rsi_val >= 75:
            bear_score += 1
            reasons.append(f"RSI şişmiş {rsi_val:.1f}")
        elif rsi_val <= 32:
            reasons.append(f"RSI dipte {rsi_val:.1f}")

    if symbol_data["price_change_percent_24h"] >= 2:
        bull_score += 1
        reasons.append(f"24s %+{symbol_data['price_change_percent_24h']:.2f}")
    elif symbol_data["price_change_percent_24h"] <= -2:
        bear_score += 1
        reasons.append(f"24s %{symbol_data['price_change_percent_24h']:.2f}")

    if bull_score >= SPOT_SIGNAL_THRESHOLD and bull_score > bear_score:
        return {
            "market": "SPOT",
            "type": "LONG",
            "symbol": symbol,
            "score": bull_score,
            "trend": trend,
            "price": last_close,
            "rsi": rsi_val,
            "volume_ratio": volume_ratio,
            "move_5": move_5,
            "move_15": move_15,
            "reasons": reasons[:6]
        }

    if bear_score >= SPOT_SIGNAL_THRESHOLD and bear_score > bull_score:
        return {
            "market": "SPOT",
            "type": "SHORT_RISK",
            "symbol": symbol,
            "score": bear_score,
            "trend": trend,
            "price": last_close,
            "rsi": rsi_val,
            "volume_ratio": volume_ratio,
            "move_5": move_5,
            "move_15": move_15,
            "reasons": reasons[:6]
        }

    return None


def scan_spot_market():
    spot_up = []
    spot_down = []
    errors = 0

    try:
        symbols = get_spot_top_symbols()
    except Exception as e:
        log(f"Spot coin listesi alınamadı: {e}")
        return [], [], 1

    log(f"Spot taranacak coin: {len(symbols)}")

    for s in symbols:
        try:
            result = analyze_spot_symbol(s)
            if result:
                if result["type"] == "LONG":
                    spot_up.append(result)
                else:
                    spot_down.append(result)
            time.sleep(0.10)
        except Exception as e:
            errors += 1
            log(f"Spot hata {s['symbol']}: {e}")

    spot_up.sort(key=lambda x: x["score"], reverse=True)
    spot_down.sort(key=lambda x: x["score"], reverse=True)

    return spot_up[:MAX_SEND_PER_GROUP], spot_down[:MAX_SEND_PER_GROUP], errors


# =========================
# ALPHA
# =========================

def get_alpha_exchange_info():
    return alpha_get_json("/bapi/defi/v1/public/alpha-trade/get-exchange-info")


def get_alpha_ticker(symbol):
    return alpha_get_json(
        "/bapi/defi/v1/public/alpha-trade/ticker",
        params={"symbol": symbol}
    )


def get_alpha_klines(symbol, interval="5m", limit=120):
    return alpha_get_json(
        "/bapi/defi/v1/public/alpha-trade/klines",
        params={"symbol": symbol, "interval": interval, "limit": limit}
    )


def get_alpha_usdt_symbols():
    ex = get_alpha_exchange_info()
    symbols = ex.get("symbols", [])
    out = []

    for s in symbols:
        try:
            if s.get("status") != "TRADING":
                continue
            if s.get("quoteAsset") != "USDT":
                continue
            out.append(s["symbol"])
        except Exception:
            continue

    return out


def parse_alpha_klines(klines):
    closes = []
    quote_volumes = []

    for k in klines:
        closes.append(float(k[4]))
        quote_volumes.append(float(k[7]))

    return closes, quote_volumes


def analyze_alpha_symbol(symbol):
    ticker = get_alpha_ticker(symbol)
    klines = get_alpha_klines(symbol, ALPHA_INTERVAL, ALPHA_KLINE_LIMIT)

    closes, volumes = parse_alpha_klines(klines)

    if len(closes) < 60:
        return None

    last = closes[-1]
    prev = closes[-2]
    c5 = closes[-6]
    c15 = closes[-16]

    move_1 = pct_change(prev, last)
    move_5 = pct_change(c5, last)
    move_15 = pct_change(c15, last)

    rsi_val = rsi(closes, 14)
    ema20 = ema(closes, 20)
    ema50 = ema(closes, 50)

    last_vol = volumes[-1]
    avg_vol = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    volume_ratio = (last_vol / avg_vol) if avg_vol > 0 else 0

    bull_score = 0
    bear_score = 0
    reasons = []
    trend = "NÖTR"

    if ema20 and ema50:
        if ema20 > ema50:
            trend = "YUKARI"
            bull_score += 2
            reasons.append("EMA20>EMA50")
        else:
            trend = "AŞAĞI"
            bear_score += 2
            reasons.append("EMA20<EMA50")

    if move_1 >= 0.5:
        bull_score += 1
        reasons.append(f"1 mum %+{move_1:.2f}")
    elif move_1 <= -0.5:
        bear_score += 1
        reasons.append(f"1 mum %{move_1:.2f}")

    if move_5 >= 1.0:
        bull_score += 2
        reasons.append(f"5 mum %+{move_5:.2f}")
    elif move_5 <= -1.0:
        bear_score += 2
        reasons.append(f"5 mum %{move_5:.2f}")

    if move_15 >= 1.8:
        bull_score += 2
        reasons.append(f"15 mum %+{move_15:.2f}")
    elif move_15 <= -1.8:
        bear_score += 2
        reasons.append(f"15 mum %{move_15:.2f}")

    if volume_ratio >= 1.3:
        if move_1 >= 0:
            bull_score += 2
            reasons.append(f"Alım hacmi x{volume_ratio:.2f}")
        else:
            bear_score += 2
            reasons.append(f"Satış hacmi x{volume_ratio:.2f}")

    if rsi_val is not None:
        if 45 <= rsi_val <= 72:
            bull_score += 1
            reasons.append(f"RSI uygun {rsi_val:.1f}")
        elif rsi_val >= 78:
            bear_score += 1
            reasons.append(f"RSI şişmiş {rsi_val:.1f}")
        elif rsi_val <= 30:
            reasons.append(f"RSI dipte {rsi_val:.1f}")

    try:
        price_change_24h = float(ticker.get("priceChangePercent", 0))
        quote_volume_24h = float(ticker.get("quoteVolume", 0))
    except Exception:
        price_change_24h = 0.0
        quote_volume_24h = 0.0

    if price_change_24h >= 2.5:
        bull_score += 1
        reasons.append(f"24s %+{price_change_24h:.2f}")
    elif price_change_24h <= -2.5:
        bear_score += 1
        reasons.append(f"24s %{price_change_24h:.2f}")

    if bull_score >= ALPHA_SIGNAL_THRESHOLD and bull_score > bear_score:
        return {
            "market": "ALPHA",
            "type": "LONG",
            "symbol": symbol,
            "score": bull_score,
            "trend": trend,
            "price": last,
            "rsi": rsi_val,
            "volume_ratio": volume_ratio,
            "move_5": move_5,
            "move_15": move_15,
            "quote_volume_24h": quote_volume_24h,
            "reasons": reasons[:6]
        }

    if bear_score >= ALPHA_SIGNAL_THRESHOLD and bear_score > bull_score:
        return {
            "market": "ALPHA",
            "type": "SHORT_RISK",
            "symbol": symbol,
            "score": bear_score,
            "trend": trend,
            "price": last,
            "rsi": rsi_val,
            "volume_ratio": volume_ratio,
            "move_5": move_5,
            "move_15": move_15,
            "quote_volume_24h": quote_volume_24h,
            "reasons": reasons[:6]
        }

    return None


def scan_alpha_market():
    alpha_up = []
    alpha_down = []
    errors = 0

    try:
        alpha_symbols = get_alpha_usdt_symbols()
    except Exception as e:
        log(f"Alpha sembolleri alınamadı: {e}")
        return [], [], 1

    alpha_symbols = alpha_symbols[:ALPHA_MAX_SYMBOLS]
    log(f"Alpha taranacak coin: {len(alpha_symbols)}")

    for symbol in alpha_symbols:
        try:
            result = analyze_alpha_symbol(symbol)
            if result:
                if result["type"] == "LONG":
                    alpha_up.append(result)
                else:
                    alpha_down.append(result)
            time.sleep(0.12)
        except Exception as e:
            errors += 1
            log(f"Alpha hata {symbol}: {e}")

    alpha_up.sort(key=lambda x: x["score"], reverse=True)
    alpha_down.sort(key=lambda x: x["score"], reverse=True)

    return alpha_up[:MAX_SEND_PER_GROUP], alpha_down[:MAX_SEND_PER_GROUP], errors


# =========================
# FORMAT
# =========================

def format_signal(item):
    signal_name = "🚀 YÜKSELİŞ ADAYI" if item["type"] == "LONG" else "🔻 DÜŞÜŞ RİSKİ"
    rsi_text = f"{item['rsi']:.1f}" if item.get("rsi") is not None else "-"
    qv24 = item.get("quote_volume_24h", None)

    lines = [
        f"<b>{signal_name}</b>",
        f"Pazar: <b>{item['market']}</b>",
        f"Coin: <b>{item['symbol']}</b>",
        f"Skor: <b>{item['score']}</b>",
        f"Trend: <b>{item['trend']}</b>",
        f"Fiyat: <b>{item['price']:.8f}</b>",
        f"RSI: <b>{rsi_text}</b>",
        f"5 Mum: <b>%{item['move_5']:.2f}</b>",
        f"15 Mum: <b>%{item['move_15']:.2f}</b>",
        f"Hacim Gücü: <b>x{item['volume_ratio']:.2f}</b>",
    ]

    if qv24 is not None:
        lines.append(f"24s Hacim: <b>{qv24:,.0f}</b>")

    lines.append(f"Nedenler: <b>{' | '.join(item['reasons'])}</b>")
    return "\n".join(lines)


def format_group(title, items):
    if not items:
        return f"{title}\nUygun coin bulunamadı."

    parts = [title]
    for idx, item in enumerate(items, start=1):
        parts.append(
            f"\n{idx}) {item['symbol']} | Skor: {item['score']} | Trend: {item['trend']} | 5M: %{item['move_5']:.2f} | 15M: %{item['move_15']:.2f}"
        )
    return "\n".join(parts)


# =========================
# MAIN
# =========================

def main():
    log("Bot çalıştı. Spot + Alpha tarama başlıyor...")

    # Test mesajı
    send_telegram("✅ Test mesajı: Bot çalıştı, tarama başlıyor.")

    spot_up, spot_down, spot_errors = scan_spot_market()
    alpha_up, alpha_down, alpha_errors = scan_alpha_market()

    total_errors = spot_errors + alpha_errors
    total_found = len(spot_up) + len(spot_down) + len(alpha_up) + len(alpha_down)

    summary = (
        f"✅ Tarama tamamlandı\n"
        f"Spot yükseliş adayı: {len(spot_up)}\n"
        f"Spot düşüş riski: {len(spot_down)}\n"
        f"Alpha yükseliş adayı: {len(alpha_up)}\n"
        f"Alpha düşüş riski: {len(alpha_down)}\n"
        f"Toplam sinyal: {total_found}\n"
        f"Hata: {total_errors}"
    )
    send_telegram(summary)

    if total_found == 0:
        send_telegram("ℹ️ Bot çalıştı ama bu turda uygun sinyal bulunamadı.")
        return

    send_telegram(format_group("📈 SPOT YÜKSELİŞ ADAYLARI", spot_up))
    send_telegram(format_group("📉 SPOT DÜŞÜŞ RİSKİ", spot_down))
    send_telegram(format_group("🧪 ALPHA YÜKSELİŞ ADAYLARI", alpha_up))
    send_telegram(format_group("⚠️ ALPHA DÜŞÜŞ RİSKİ", alpha_down))

    for item in spot_up + spot_down + alpha_up + alpha_down:
        send_telegram(format_signal(item))


if __name__ == "__main__":
    main()
