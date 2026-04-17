import os
from datetime import datetime

import pandas as pd
import requests

# =========================================================
# TELEGRAM
# =========================================================
TELEGRAM_TOKEN = os.getenv("8701403795:AAFH5W28DmP1TVXRBCfZYn3wOiC8w8wEuAU", "")
TELEGRAM_CHAT_ID = os.getenv("768262682", "")

def send_telegram(text: str) -> None:
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram ayarları eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
    }

    try:
        r = requests.post(url, data=payload, timeout=20)
        print("Telegram status:", r.status_code)
        print("Telegram response:", r.text[:300])
    except Exception as e:
        print("Telegram gönderim hatası:", e)


# =========================================================
# AYARLAR
# =========================================================
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

MIN_1H_CHANGE = 3.0
MIN_VOLUME_USD = 5_000_000
MAX_COINS_TO_SCAN = 15

INTERVAL = "15m"
LIMIT = 220
PIVOT_LEN = 20

RSI_LEN = 14
EMA_FAST = 20


# =========================================================
# VERİ ÇEKME
# =========================================================
def get_rapid_movers():
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 100,
        "page": 1,
        "price_change_percentage": "1h",
    }

    try:
        r = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=30)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        print("CoinGecko veri çekme hatası:", e)
        return []

    movers = []
    for coin in data:
        symbol = str(coin.get("symbol", "")).upper().strip()
        change_1h = coin.get("price_change_percentage_1h_in_currency")
        volume = float(coin.get("total_volume") or 0)
        price = float(coin.get("current_price") or 0)

        if not symbol or change_1h is None:
            continue

        try:
            change_1h = float(change_1h)
        except Exception:
            continue

        if abs(change_1h) >= MIN_1H_CHANGE and volume >= MIN_VOLUME_USD:
            movers.append({
                "symbol": symbol,
                "price": price,
                "change": change_1h,
                "volume": volume,
            })

    movers.sort(key=lambda x: abs(x["change"]), reverse=True)
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

        if len(df) < 100:
            return None

        return df

    except Exception as e:
        print(f"{symbol}USDT veri çekme hatası:", e)
        return None


# =========================================================
# GÖSTERGELER
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


# =========================================================
# PIVOT / DİP / TEPE
# =========================================================
def detect_pivots(df: pd.DataFrame, pivot_len: int = 20) -> pd.DataFrame:
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

    df["dip"] = pivot_low
    df["tepe"] = pivot_high
    return df


# =========================================================
# ANALİZ
# =========================================================
def analyze_symbol(symbol: str):
    df = get_klines(symbol)
    if df is None:
        return None

    df["ema20"] = ema(df["close"], EMA_FAST)
    df["rsi"] = rsi(df["close"], RSI_LEN)
    df = detect_pivots(df, PIVOT_LEN)

    df["dip_cond"] = df["dip"] & (df["rsi"] < 38)
    df["tepe_cond"] = df["tepe"] & (df["rsi"] > 62)

    last = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3]

    recent_dip = bool(last["dip_cond"] or prev1["dip_cond"] or prev2["dip_cond"])
    recent_tepe = bool(last["tepe_cond"] or prev1["tepe_cond"] or prev2["tepe_cond"])

    buy_now = bool(prev2["dip_cond"] and last["close"] > last["ema20"])
    sell_now = bool(prev2["tepe_cond"] and last["close"] < last["ema20"])

    return {
        "price": float(last["close"]),
        "dip": recent_dip,
        "tepe": recent_tepe,
        "buy": buy_now,
        "sell": sell_now,
    }


# =========================================================
# MESAJ
# =========================================================
def format_message(coin: dict, analysis: dict):
    symbol = coin["symbol"]
    price = coin["price"]
    change = coin["change"]
    volume = coin["volume"]

    direction = "🚀 YÜKSELİŞ" if change > 0 else "📉 DÜŞÜŞ"

    strength = "ZAYIF"
    if abs(change) > 5:
        strength = "ORTA"
    if abs(change) > 8:
        strength = "GÜÇLÜ"

    # Sadece orta ve güçlü
    if strength == "ZAYIF":
        return None

    signals = []

    if analysis["dip"]:
        signals.append("🟢 DİP")
    if analysis["tepe"]:
        signals.append("🔴 TEPE")
    if analysis["buy"]:
        signals.append("✅ AL")
    if analysis["sell"]:
        signals.append("⛔ SAT")

    if not signals:
        return None

    msg = f"""🔥 RAPID MOVEMENT TESPİT

Coin: {symbol}
Fiyat: ${price}

Değişim (1h): %{round(change, 2)}
Hacim: ${volume}

Yön: {direction}
Güç: {strength}

Sinyal: {" | ".join(signals)}

Zaman: {datetime.now().strftime('%H:%M:%S')}"""

    return msg


# =========================================================
# ANA ÇALIŞMA
# =========================================================
def run_once():
    print("Bot başladı...")

    movers = get_rapid_movers()
    print(f"Rapid mover bulundu: {len(movers)}")

    if not movers:
        send_telegram("ℹ️ Rapid mover bulunamadı.")
        return

    sent_count = 0

    for coin in movers:
        symbol = coin["symbol"]
        print(f"Analiz ediliyor: {symbol}USDT")

        analysis = analyze_symbol(symbol)
        if not analysis:
            print(f"Analiz başarısız: {symbol}")
            continue

        msg = format_message(coin, analysis)
        print(f"Mesaj üretildi mi? {'EVET' if msg else 'HAYIR'}")

        if msg:
            print(msg)
            send_telegram(msg)
            sent_count += 1

    if sent_count == 0:
        send_telegram("✅ Bot çalıştı ama bu turda uygun ORTA veya GÜÇLÜ sinyal bulunamadı.")

    print(f"Toplam gönderilen mesaj: {sent_count}")


if __name__ == "__main__":
    run_once()
send_telegram("🚀 TEST MESAJI - BOT ÇALIŞIYOR")
