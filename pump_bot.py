import os
from datetime import datetime

import pandas as pd
import requests

# =========================================================
# TELEGRAM
# =========================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

def send_telegram(text: str) -> bool:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarlari eksik.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }

    try:
        r = requests.post(url, data=payload, timeout=20)
        print("Telegram status:", r.status_code)
        print("Telegram response:", r.text[:300])
        return r.status_code == 200
    except Exception as e:
        print("Telegram gonderim hatasi:", e)
        return False


# =========================================================
# AYARLAR
# =========================================================
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

# Fazla gereksiz sinyal gelmesin diye daha secici ayarlar
MIN_1H_CHANGE = 2.5
MIN_VOLUME_USD = 8_000_000
MAX_COINS_TO_SCAN = 20

INTERVAL = "15m"
LIMIT = 260
PIVOT_LEN = 12

RSI_LEN = 14
EMA_FAST = 20
EMA_SLOW = 50
VOLUME_MA_LEN = 20


# =========================================================
# VERI CEKME
# =========================================================
def get_rapid_movers():
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 100,
        "page": 1,
        "price_change_percentage": "1h,24h",
    }

    try:
        r = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("CoinGecko veri cekme hatasi:", e)
        return []

    movers = []
    blocked_symbols = {
        "USDT", "USDC", "BUSD", "DAI", "FDUSD", "TUSD", "USDE", "PYUSD"
    }

    for coin in data:
        symbol = str(coin.get("symbol", "")).upper().strip()
        change_1h = coin.get("price_change_percentage_1h_in_currency")
        change_24h = coin.get("price_change_percentage_24h_in_currency")
        volume = float(coin.get("total_volume") or 0)
        price = float(coin.get("current_price") or 0)

        if not symbol or symbol in blocked_symbols:
            continue

        if change_1h is None:
            continue

        try:
            change_1h = float(change_1h)
            change_24h = float(change_24h) if change_24h is not None else 0.0
        except Exception:
            continue

        if abs(change_1h) < MIN_1H_CHANGE:
            continue

        if volume < MIN_VOLUME_USD:
            continue

        movers.append({
            "symbol": symbol,
            "price": price,
            "change_1h": change_1h,
            "change_24h": change_24h,
            "volume": volume,
        })

    movers.sort(
        key=lambda x: (abs(x["change_1h"]), x["volume"]),
        reverse=True
    )
    return movers[:MAX_COINS_TO_SCAN]


def get_klines(symbol: str):
    params = {
        "symbol": f"{symbol}USDT",
        "interval": INTERVAL,
        "limit": LIMIT,
    }

    try:
        r = requests.get(BINANCE_KLINES_URL, params=params, timeout=30)
        if r.status_code != 200:
            print(f"{symbol}USDT Binance status:", r.status_code)
            return None

        raw = r.json()
        if not isinstance(raw, list) or not raw:
            return None

        df = pd.DataFrame(raw)
        df = df[[1, 2, 3, 4, 5]]
        df.columns = ["open", "high", "low", "close", "volume"]

        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df.dropna(inplace=True)

        if len(df) < 120:
            return None

        return df.reset_index(drop=True)

    except Exception as e:
        print(f"{symbol}USDT veri cekme hatasi:", e)
        return None


# =========================================================
# GOSTERGELER
# =========================================================
def ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


def rsi(series: pd.Series, length: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.rolling(length).mean()
    avg_loss = loss.rolling(length).mean()

    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def detect_pivots(df: pd.DataFrame, pivot_len: int = 12) -> pd.DataFrame:
    lows = df["low"].tolist()
    highs = df["high"].tolist()

    pivot_low = [False] * len(df)
    pivot_high = [False] * len(df)

    for i in range(pivot_len, len(df) - pivot_len):
        low_window = lows[i - pivot_len:i + pivot_len + 1]
        high_window = highs[i - pivot_len:i + pivot_len + 1]

        if lows[i] == min(low_window):
            pivot_low[i] = True

        if highs[i] == max(high_window):
            pivot_high[i] = True

    df["pivot_low"] = pivot_low
    df["pivot_high"] = pivot_high
    return df


# =========================================================
# PUANLAMA
# =========================================================
def get_strength_and_score(change_1h: float, analysis: dict):
    score = 0

    if abs(change_1h) >= 2.5:
        score += 1
    if abs(change_1h) >= 4:
        score += 1
    if abs(change_1h) >= 6:
        score += 1

    if analysis["volume_ratio"] >= 1.2:
        score += 1
    if analysis["volume_ratio"] >= 1.8:
        score += 1

    if analysis["trend_up"] or analysis["trend_down"]:
        score += 1

    if analysis["buy"]:
        score += 2
    if analysis["sell"]:
        score += 2

    if analysis["recent_dip"] or analysis["recent_tepe"]:
        score += 1

    if score <= 3:
        return "ZAYIF", score
    if score <= 6:
        return "ORTA", score
    return "GUCLU", score


# =========================================================
# ANALIZ
# =========================================================
def analyze_symbol(symbol: str):
    df = get_klines(symbol)
    if df is None:
        return None

    df["ema20"] = ema(df["close"], EMA_FAST)
    df["ema50"] = ema(df["close"], EMA_SLOW)
    df["rsi"] = rsi(df["close"], RSI_LEN)
    df["vol_ma"] = df["volume"].rolling(VOLUME_MA_LEN).mean()
    df = detect_pivots(df, PIVOT_LEN)

    last = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3]
    prev3 = df.iloc[-4]

    volume_ratio = float(last["volume"] / last["vol_ma"]) if last["vol_ma"] and last["vol_ma"] > 0 else 0.0

    trend_up = bool(last["close"] > last["ema20"] > last["ema50"])
    trend_down = bool(last["close"] < last["ema20"] < last["ema50"])

    recent_dip = bool(last["pivot_low"] or prev1["pivot_low"] or prev2["pivot_low"])
    recent_tepe = bool(last["pivot_high"] or prev1["pivot_high"] or prev2["pivot_high"])

    # Daha secici al/sat sinyali
    buy = bool(
        recent_dip
        and trend_up
        and 42 <= float(last["rsi"]) <= 62
        and volume_ratio >= 1.15
        and last["close"] > prev1["close"] > prev2["close"]
    )

    sell = bool(
        recent_tepe
        and trend_down
        and 38 <= float(last["rsi"]) <= 58
        and volume_ratio >= 1.15
        and last["close"] < prev1["close"] < prev2["close"]
    )

    # Gürültülü yerleri ele
    weak_zone = bool(
        (not buy and not sell)
        and volume_ratio < 1.05
    )

    # Son birkaç mum çok sıkışık ise ele
    recent_range_pct = float(((df["high"].tail(4).max() - df["low"].tail(4).min()) / last["close"]) * 100)

    return {
        "price": float(last["close"]),
        "rsi": float(last["rsi"]),
        "ema20": float(last["ema20"]),
        "ema50": float(last["ema50"]),
        "volume_ratio": volume_ratio,
        "trend_up": trend_up,
        "trend_down": trend_down,
        "recent_dip": recent_dip,
        "recent_tepe": recent_tepe,
        "buy": buy,
        "sell": sell,
        "weak_zone": weak_zone,
        "recent_range_pct": recent_range_pct,
        "last_close_up": bool(last["close"] > prev1["close"] > prev2["close"] > prev3["close"]),
        "last_close_down": bool(last["close"] < prev1["close"] < prev2["close"] < prev3["close"]),
    }


# =========================================================
# MESAJ
# =========================================================
def format_signal_message(coin: dict, analysis: dict):
    symbol = coin["symbol"]
    price = analysis["price"]
    change_1h = coin["change_1h"]
    change_24h = coin["change_24h"]
    volume = coin["volume"]

    # Gürültülü coinleri direk ele
    if analysis["weak_zone"]:
        return None

    if analysis["recent_range_pct"] < 1.2:
        return None

    if not analysis["buy"] and not analysis["sell"]:
        return None

    strength, score = get_strength_and_score(change_1h, analysis)

    # Sadece orta ve guclu gelsin
    if strength == "ZAYIF":
        return None

    direction = "YUKARI" if change_1h > 0 else "ASAGI"
    trend_text = "YUKSELIS TRENDI" if analysis["trend_up"] else "DUSUS TRENDI" if analysis["trend_down"] else "KARARSIZ"

    signal_text = "AL" if analysis["buy"] else "SAT"

    msg = (
        f"RAPID DIP TEPE PRO\n\n"
        f"Coin: {symbol}\n"
        f"Fiyat: ${price:.6f}\n"
        f"1 Saat: %{change_1h:.2f}\n"
        f"24 Saat: %{change_24h:.2f}\n"
        f"Hacim: ${volume:,.0f}\n\n"
        f"Yon: {direction}\n"
        f"Trend: {trend_text}\n"
        f"Guc: {strength}\n"
        f"Skor: {score}/8\n"
        f"RSI: {analysis['rsi']:.2f}\n"
        f"Hacim Katsayisi: {analysis['volume_ratio']:.2f}x\n"
        f"Sinyal: {signal_text}\n"
        f"Zaman: {datetime.now().strftime('%H:%M:%S')}"
    )
    return msg


def format_run_summary(total_movers: int, scanned_count: int, sent_count: int, rejected_count: int) -> str:
    return (
        f"BOT DURUM RAPORU\n\n"
        f"Taranan mover: {total_movers}\n"
        f"Analiz edilen: {scanned_count}\n"
        f"Elenen: {rejected_count}\n"
        f"Gonderilen sinyal: {sent_count}\n"
        f"Zaman: {datetime.now().strftime('%H:%M:%S')}"
    )


# =========================================================
# ANA CALISMA
# =========================================================
def run_once():
    print("Bot basladi...")
    send_telegram("Bot calisti. Pro tarama basliyor...")

    movers = get_rapid_movers()
    print(f"Rapid mover bulundu: {len(movers)}")

    if not movers:
        send_telegram("Rapid mover bulunamadi.")
        return

    sent_count = 0
    scanned_count = 0
    rejected_count = 0

    for coin in movers:
        symbol = coin["symbol"]
        print(f"Analiz ediliyor: {symbol}USDT")

        analysis = analyze_symbol(symbol)
        if not analysis:
            print(f"Analiz basarisiz: {symbol}")
            rejected_count += 1
            continue

        scanned_count += 1

        msg = format_signal_message(coin, analysis)
        print(f"Mesaj uretildi mi? {'EVET' if msg else 'HAYIR'}")

        if msg:
            print(msg)
            if send_telegram(msg):
                sent_count += 1
        else:
            rejected_count += 1

    send_telegram(format_run_summary(len(movers), scanned_count, sent_count, rejected_count))

    if sent_count == 0:
        send_telegram("Bu turda filtreyi gecen ORTA veya GUCLU sinyal bulunamadi.")

    print(f"Toplam gonderilen mesaj: {sent_count}")


if __name__ == "__main__":
    run_once()
