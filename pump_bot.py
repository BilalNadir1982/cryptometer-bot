import os
import time
import math
import requests
from datetime import datetime, timezone

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

# Public market data için bu endpoint güvenli seçim
BASE_URL = "https://data-api.binance.vision"

INTERVAL = "5m"
TOP_SYMBOLS_LIMIT = 50
SIGNAL_SCORE_THRESHOLD = 5
MIN_QUOTE_VOLUME_USDT = 7_500_000  # aşırı ölü coinleri ele
SIGNAL_SCORE_THRESHOLD = 5

REQUEST_TIMEOUT = 20


def log(msg: str):
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def send_telegram(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        log("Telegram env eksik, mesaj atlanıyor.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        log(f"Telegram status: {r.status_code}")
        if r.status_code != 200:
            log(f"Telegram response: {r.text}")
    except Exception as e:
        log(f"Telegram gönderim hatası: {e}")


def get_json(url: str, params=None):
    r = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
    r.raise_for_status()
    return r.json()


def get_top_symbols():
    """
    USDT paritelerini, 24h quote volume'a göre sıralar.
    """
    data = get_json(f"{BASE_URL}/api/v3/ticker/24hr")
    symbols = []

    for item in data:
        symbol = item.get("symbol", "")
        if not symbol.endswith("USDT"):
            continue

        # Kaldıraç tokenlarını ve çok alakasızları temizle
        banned_parts = ["UPUSDT", "DOWNUSDT", "BULLUSDT", "BEARUSDT"]
        if any(bp in symbol for bp in banned_parts):
            continue

        try:
            quote_volume = float(item.get("quoteVolume", 0))
            last_price = float(item.get("lastPrice", 0))
            price_change_percent = float(item.get("priceChangePercent", 0))
        except:
            continue

        if quote_volume < MIN_QUOTE_VOLUME_USDT:
            continue
        if last_price <= 0:
            continue

        symbols.append({
            "symbol": symbol,
            "quote_volume": quote_volume,
            "price_change_percent_24h": price_change_percent,
        })

    symbols.sort(key=lambda x: x["quote_volume"], reverse=True)
    return symbols[:TOP_SYMBOLS_LIMIT]


def get_klines(symbol: str, interval="5m", limit=120):
    data = get_json(
        f"{BASE_URL}/api/v3/klines",
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


def pct_change(a, b):
    if a == 0:
        return 0
    return ((b - a) / a) * 100


def analyze_symbol(symbol_data):
    symbol = symbol_data["symbol"]
    candles = get_klines(symbol, INTERVAL, KLINE_LIMIT)

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
    avg_vol_20 = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else sum(volumes[:-1]) / max(len(volumes)-1, 1)

    move_1_candle = pct_change(prev_close, last_close)
    move_5m_window = pct_change(close_5, last_close)
    move_15m_window = pct_change(close_15, last_close)
    volume_ratio = (last_vol / avg_vol_20) if avg_vol_20 > 0 else 0

    score = 0
    reasons = []

    # 1) son mum hareketi
    if move_1_candle >= 0.8:
        score += 1
        reasons.append(f"1 mum %+{move_1_candle:.2f}")

    # 2) son 5 mum hareketi
    if move_5m_window >= 1.8:
        score += 2
        reasons.append(f"5 mum %+{move_5m_window:.2f}")

    # 3) son 15 mum hareketi
    if move_15m_window >= 2.8:
        score += 2
        reasons.append(f"15 mum %+{move_15m_window:.2f}")

    # 4) hacim patlaması
    if volume_ratio >= 1.8:
        score += 2
        reasons.append(f"Hacim x{volume_ratio:.2f}")

    # 5) trend filtresi
    trend = "NÖTR"
    if ema_20 and ema_50:
        if ema_20 > ema_50:
            trend = "YUKARI"
            score += 1
            reasons.append("EMA20 > EMA50")
        else:
            trend = "AŞAĞI"

    # 6) RSI mantığı - aşırı şişmişleri direkt övme, ama momentum da kaçmasın
    if rsi_val is not None:
        if 52 <= rsi_val <= 68:
            score += 1
            reasons.append(f"RSI uygun {rsi_val:.1f}")
        elif rsi_val > 80:
            score -= 1
            reasons.append(f"RSI çok şişmiş {rsi_val:.1f}")

    # 7) 24h genel filtre
    if symbol_data["price_change_percent_24h"] >= 3:
        score += 1
        reasons.append(f"24s %+{symbol_data['price_change_percent_24h']:.2f}")

    if score < SIGNAL_SCORE_THRESHOLD:
        return None

    if score >= 7:
        strength = "🔥 GÜÇLÜ"
    elif score >= 5:
        strength = "⚡ ORTA"
    else:
        strength = "🟡 ZAYIF"

    return {
        "symbol": symbol,
        "score": score,
        "strength": strength,
        "trend": trend,
        "rsi": rsi_val,
        "move_1_candle": move_1_candle,
        "move_5m_window": move_5m_window,
        "move_15m_window": move_15m_window,
        "volume_ratio": volume_ratio,
        "quote_volume_24h": symbol_data["quote_volume"],
        "reasons": reasons,
        "price": last_close,
    }


def format_signal(s):
    return (
        f"<b>{s['strength']} SİNYAL</b>\n"
        f"Coin: <b>{s['symbol']}</b>\n"
        f"Skor: <b>{s['score']}</b>\n"
        f"Trend: <b>{s['trend']}</b>\n"
        f"Fiyat: <b>{s['price']:.6f}</b>\n"
        f"RSI: <b>{s['rsi']:.1f}</b>\n"
        f"1 Mum: <b>%{s['move_1_candle']:.2f}</b>\n"
        f"5 Mum: <b>%{s['move_5m_window']:.2f}</b>\n"
        f"15 Mum: <b>%{s['move_15m_window']:.2f}</b>\n"
        f"Hacim Gücü: <b>x{s['volume_ratio']:.2f}</b>\n"
        f"24s Hacim: <b>{s['quote_volume_24h']:,.0f} USDT</b>\n"
        f"Nedenler: <b>{' | '.join(s['reasons'])}</b>"
    )


def main():
    log("Bot çalıştı. Tarama başlıyor...")

    try:
        symbols = get_top_symbols()
        log(f"Taranacak coin sayısı: {len(symbols)}")
    except Exception as e:
        log(f"Coin listesi alınamadı: {e}")
        send_telegram(f"❌ Coin listesi alınamadı: {e}")
        return

    found = []
    errors = 0

    for s in symbols:
        symbol = s["symbol"]
        try:
            result = analyze_symbol(s)
            if result:
                found.append(result)
                log(f"Sinyal bulundu: {symbol} | skor={result['score']}")
            else:
                log(f"Pas: {symbol}")
            time.sleep(0.15)
        except Exception as e:
            errors += 1
            log(f"Hata {symbol}: {e}")

    found.sort(key=lambda x: x["score"], reverse=True)

    if not found:
        text = (
            "ℹ️ Bot çalıştı ama bu turda eşik üstü sinyal bulunamadı.\n"
            f"Taranan coin: {len(symbols)}\n"
            f"Hata: {errors}\n"
            f"Interval: {INTERVAL}\n"
            f"Eşik skor: {SIGNAL_SCORE_THRESHOLD}"
        )
        send_telegram(text)
        log(text)
        return

    # En iyi 5 sinyali gönder
    send_telegram(
        f"✅ Tarama bitti\n"
        f"Taranan coin: {len(symbols)}\n"
        f"Bulunan sinyal: {len(found)}\n"
        f"Hata: {errors}\n"
        f"Interval: {INTERVAL}"
    )

    for sig in found[:5]:
        send_telegram(format_signal(sig))


if __name__ == "__main__":
    main()
