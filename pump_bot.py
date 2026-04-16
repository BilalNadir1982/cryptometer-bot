import os
import time
import math
import requests
import pandas as pd
from datetime import datetime

# ====================================================
# AYARLAR
# ====================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "8701403795:AAFH5W28DmP1TVXRBCfZYn3wOiC8w8wEuAU")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "768262682")

COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

CHECK_INTERVAL_SEC = 300        # 5 dk
MAX_COINS_TO_SCAN = 15          # rapid mover içinden teknik analize sokulacak coin sayısı
COOLDOWN_SEC = 3600             # aynı coin için 1 saat susturma

# Rapid mover ayarları
MIN_1H_CHANGE = 3.0             # %1h değişim
MIN_VOLUME_USD = 5_000_000      # minimum hacim
RAPID_VOLUME_MULT = 1.5         # hacim ort. çarpanı
RAPID_ATR_MULT = 1.2            # ATR bazlı hızlı hareket filtresi
RAPID_BODY_PCT = 0.35           # mum gövde/oran filtresi

# Teknik ayarlar
RSI_LEN = 14
EMA_FAST = 20
EMA_MID = 50
EMA_SLOW = 200
ATR_LEN = 14
VOL_LEN = 20
PIVOT_LEN = 20                  # İSTEDİĞİN GİBİ SABİT 20
TREND_BUY_MIN = 60
TREND_SELL_MAX = 40

# Zaman dilimi
INTERVAL = "15m"
LIMIT = 260                     # EMA200 + pivot + hesaplar için yeterli veri

last_sent = {}

# ====================================================
# TELEGRAM
# ====================================================
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        requests.post(url, data=payload, timeout=15)
    except Exception as e:
        print("Telegram gönderim hatası:", e)

# ====================================================
# VERİ ÇEKME
# ====================================================
def get_rapid_movers():
    params = {
        "vs_currency": "usd",
        "order": "volume_desc",
        "per_page": 100,
        "page": 1,
        "price_change_percentage": "1h,24h"
    }
    r = requests.get(COINGECKO_MARKETS_URL, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    movers = []
    for coin in data:
        symbol = coin.get("symbol", "").upper()
        change_1h = coin.get("price_change_percentage_1h_in_currency")
        volume = coin.get("total_volume", 0)
        price = coin.get("current_price", 0)

        if not symbol or change_1h is None:
            continue

        if abs(change_1h) >= MIN_1H_CHANGE and volume >= MIN_VOLUME_USD:
            movers.append({
                "symbol": symbol,
                "price": price,
                "change_1h": change_1h,
                "volume": volume
            })

    movers.sort(key=lambda x: abs(x["change_1h"]), reverse=True)
    return movers[:MAX_COINS_TO_SCAN]

def get_binance_klines(symbol: str, interval: str = INTERVAL, limit: int = LIMIT):
    pair = f"{symbol}USDT"
    params = {
        "symbol": pair,
        "interval": interval,
        "limit": limit
    }
    r = requests.get(BINANCE_KLINES_URL, params=params, timeout=20)
    if r.status_code != 200:
        return None

    raw = r.json()
    if not isinstance(raw, list):
        return None

    cols = [
        "open_time", "open", "high", "low", "close", "volume",
        "close_time", "qav", "trades", "tbbav", "tbqav", "ignore"
    ]
    df = pd.DataFrame(raw, columns=cols)
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["open_time"] = pd.to_datetime(df["open_time"], unit="ms")
    return df

# ====================================================
# GÖSTERGE HESAPLARI
# ====================================================
def ema(series, length):
    return series.ewm(span=length, adjust=False).mean()

def rsi(series, length=14):
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/length, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/length, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def atr(df, length=14):
    high_low = df["high"] - df["low"]
    high_close = (df["high"] - df["close"].shift()).abs()
    low_close = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1/length, adjust=False).mean()

def macd(series, fast=12, slow=26, signal=9):
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    hist = macd_line - signal_line
    return macd_line, signal_line, hist

def calc_adx(df, length=14):
    high = df["high"]
    low = df["low"]
    close = df["close"]

    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        [u if (u > d and u > 0) else 0 for u, d in zip(up_move.fillna(0), down_move.fillna(0))],
        index=df.index
    )
    minus_dm = pd.Series(
        [d if (d > u and d > 0) else 0 for u, d in zip(up_move.fillna(0), down_move.fillna(0))],
        index=df.index
    )

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_rma = tr.ewm(alpha=1/length, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1/length, adjust=False).mean() / atr_rma.replace(0, 1e-10)
    minus_di = 100 * minus_dm.ewm(alpha=1/length, adjust=False).mean() / atr_rma.replace(0, 1e-10)

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, 1e-10)
    adx = dx.ewm(alpha=1/length, adjust=False).mean()
    return plus_di, minus_di, adx

# ====================================================
# PIVOT / DİP / TEPE
# ====================================================
def detect_pivots(df, pivot_len=20):
    lows = df["low"].tolist()
    highs = df["high"].tolist()
    n = len(df)

    pivot_low = [False] * n
    pivot_high = [False] * n

    for i in range(pivot_len, n - pivot_len):
        low_window = lows[i - pivot_len:i + pivot_len + 1]
        high_window = highs[i - pivot_len:i + pivot_len + 1]

        if lows[i] == min(low_window):
            pivot_low[i] = True
        if highs[i] == max(high_window):
            pivot_high[i] = True

    df["pivot_low"] = pivot_low
    df["pivot_high"] = pivot_high
    return df

# ====================================================
# TREND YÜZDESİ
# ====================================================
def calc_trend_pct(row):
    score = 0
    score += 1 if row["ema20"] > row["ema50"] else -1
    score += 1 if row["ema50"] > row["ema200"] else -1
    score += 1 if row["close"] > row["ema20"] else -1
    score += 1 if row["rsi"] > 50 else -1
    score += 1 if row["macd"] > row["macd_signal"] else -1
    score += 1 if row["adx"] > 22 else 0
    score += 1 if row["volume"] > row["vol_ma"] * 1.2 else -1

    pct = round(50 + (score / 7 * 50))
    return max(0, min(100, pct))

# ====================================================
# ANALİZ
# ====================================================
def analyze_symbol(symbol: str):
    df = get_binance_klines(symbol)
    if df is None or len(df) < 230:
        return None

    df["ema20"] = ema(df["close"], EMA_FAST)
    df["ema50"] = ema(df["close"], EMA_MID)
    df["ema200"] = ema(df["close"], EMA_SLOW)
    df["rsi"] = rsi(df["close"], RSI_LEN)
    df["atr"] = atr(df, ATR_LEN)
    df["vol_ma"] = df["volume"].rolling(VOL_LEN).mean()

    df["macd"], df["macd_signal"], _ = macd(df["close"])
    _, _, df["adx"] = calc_adx(df, RSI_LEN)

    df = detect_pivots(df, PIVOT_LEN)

    # Dip/tepe şartları
    df["dip_cond"] = df["pivot_low"] & (df["rsi"] < 38)
    df["tepe_cond"] = df["pivot_high"] & (df["rsi"] > 62)

    # Trend %
    df["trend_pct"] = df.apply(calc_trend_pct, axis=1)

    # Rapid movement iç filtre
    candle_range = (df["high"] - df["low"]).replace(0, 1e-10)
    candle_body = (df["close"] - df["open"]).abs()
    body_ratio = candle_body / candle_range

    df["rapid_up"] = (
        ((df["close"] - df["open"]) > df["atr"] * RAPID_ATR_MULT) &
        (df["volume"] > df["vol_ma"] * RAPID_VOLUME_MULT) &
        (body_ratio > RAPID_BODY_PCT)
    )

    df["rapid_down"] = (
        ((df["open"] - df["close"]) > df["atr"] * RAPID_ATR_MULT) &
        (df["volume"] > df["vol_ma"] * RAPID_VOLUME_MULT) &
        (body_ratio > RAPID_BODY_PCT)
    )

    # 2 mum sonra sinyal
    df["buy_signal"] = (
        df["dip_cond"].shift(2).fillna(False) &
        (df["trend_pct"] >= TREND_BUY_MIN) &
        (df["close"] > df["ema20"]) &
        (df["macd"] > df["macd_signal"]) &
        (df["volume"] > df["vol_ma"] * 1.3) &
        (df["rapid_up"] | (df["close"] > df["ema50"]))
    )

    df["sell_signal"] = (
        df["tepe_cond"].shift(2).fillna(False) &
        (df["trend_pct"] <= TREND_SELL_MAX) &
        (df["close"] < df["ema20"]) &
        (df["macd"] < df["macd_signal"]) &
        (df["volume"] > df["vol_ma"] * 1.3) &
        (df["rapid_down"] | (df["close"] < df["ema50"]))
    )

    # Sert düşüş
    df["hard_drop"] = (
        ((df["open"] - df["close"]) > df["atr"] * 2.3) &
        (df["close"] < df["ema20"]) &
        (df["rsi"] < 45)
    )

    last = df.iloc[-1]
    prev1 = df.iloc[-2]
    prev2 = df.iloc[-3]

    result = {
        "symbol": symbol,
        "price": float(last["close"]),
        "trend_pct": int(last["trend_pct"]),
        "rsi": float(last["rsi"]),
        "adx": float(last["adx"]),
        "ema20": float(last["ema20"]),
        "ema50": float(last["ema50"]),
        "ema200": float(last["ema200"]),
        "dip_now": bool(last["dip_cond"]),
        "tepe_now": bool(last["tepe_cond"]),
        "buy_now": bool(last["buy_signal"]),
        "sell_now": bool(last["sell_signal"]),
        "hard_drop_now": bool(last["hard_drop"]),
        "rapid_up_now": bool(last["rapid_up"]),
        "rapid_down_now": bool(last["rapid_down"]),
        "time": str(last["open_time"]),
    }

    # Son birkaç mumda oluşmuş pivotu da yakalayalım
    recent_dip = bool(last["dip_cond"] or prev1["dip_cond"] or prev2["dip_cond"])
    recent_tepe = bool(last["tepe_cond"] or prev1["tepe_cond"] or prev2["tepe_cond"])

    result["recent_dip"] = recent_dip
    result["recent_tepe"] = recent_tepe

    return result

# ====================================================
# MESAJ OLUŞTURMA
# ====================================================
def format_message(market_info, analysis):
    symbol = analysis["symbol"]
    price = analysis["price"]
    trend_pct = analysis["trend_pct"]
    rsi_val = analysis["rsi"]
    adx_val = analysis["adx"]
    change_1h = market_info["change_1h"]
    volume = market_info["volume"]

    signals = []
    if analysis["recent_dip"]:
        signals.append("🟢 DİP")
    if analysis["recent_tepe"]:
        signals.append("🔴 TEPE")
    if analysis["buy_now"]:
        signals.append("✅ AL")
    if analysis["sell_now"]:
        signals.append("⛔ SAT")
    if analysis["hard_drop_now"]:
        signals.append("🟣 SERT DÜŞÜŞ")
    if analysis["rapid_up_now"]:
        signals.append("🚀 RAPID UP")
    if analysis["rapid_down_now"]:
        signals.append("📉 RAPID DOWN")

    if not signals:
        return None

    trend_text = "KARARSIZ"
    if trend_pct >= 60:
        trend_text = "YÜKSELİŞ"
    elif trend_pct <= 40:
        trend_text = "DÜŞÜŞ"

    msg = (
        f"<b>{symbol}USDT</b>\n"
        f"Fiyat: <b>{price:.6f}</b>\n"
        f"1s Değişim: <b>{change_1h:.2f}%</b>\n"
        f"Hacim: <b>${volume:,.0f}</b>\n"
        f"Trend: <b>{trend_text}</b>\n"
        f"Trend %: <b>{trend_pct}</b>\n"
        f"RSI: <b>{rsi_val:.2f}</b>\n"
        f"ADX: <b>{adx_val:.2f}</b>\n"
        f"Pivot: <b>20</b>\n"
        f"Sinyal: <b>{' | '.join(signals)}</b>\n"
        f"Zaman: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}"
    )
    return msg

# ====================================================
# ANA DÖNGÜ
# ====================================================
def should_send(symbol, signal_key):
    now = time.time()
    key = f"{symbol}_{signal_key}"
    last_time = last_sent.get(key, 0)
    if now - last_time >= COOLDOWN_SEC:
        last_sent[key] = now
        return True
    return False

def run():
    print("Bot başladı...")
    send_telegram("✅ Rapid Movement + Dip/Tepe + AL/SAT bot aktif")

    while True:
        try:
            movers = get_rapid_movers()
            print(f"Rapid mover bulundu: {len(movers)}")

            for coin in movers:
                symbol = coin["symbol"]

                analysis = analyze_symbol(symbol)
                if not analysis:
                    continue

                msg = format_message(coin, analysis)
                if not msg:
                    continue

                signal_key_parts = []
                if analysis["recent_dip"]:
                    signal_key_parts.append("dip")
                if analysis["recent_tepe"]:
                    signal_key_parts.append("tepe")
                if analysis["buy_now"]:
                    signal_key_parts.append("buy")
                if analysis["sell_now"]:
                    signal_key_parts.append("sell")
                if analysis["hard_drop_now"]:
                    signal_key_parts.append("harddrop")
                if analysis["rapid_up_now"]:
                    signal_key_parts.append("rapidup")
                if analysis["rapid_down_now"]:
                    signal_key_parts.append("rapiddown")

                signal_key = "_".join(signal_key_parts) if signal_key_parts else "generic"

                if should_send(symbol, signal_key):
                    print(f"Mesaj gönderildi: {symbol}")
                    send_telegram(msg)

                time.sleep(1.2)

        except Exception as e:
            print("HATA:", e)

        time.sleep(CHECK_INTERVAL_SEC)

if __name__ == "__main__":
    run()
