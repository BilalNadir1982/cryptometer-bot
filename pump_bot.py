import os
import requests
from typing import Dict, List, Optional, Tuple

# ==========================================
# GITHUB SECRETS / AYARLAR
# ==========================================
CRYPTOMETER_API_KEY = os.getenv("CRYPTOMETER_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EXCHANGE_SPOT = "binance"
TIMEFRAME = "15m"
TOP_CANDIDATES = 15
MIN_NETFLOW_USD = 100000
MIN_LARGE_TRADE_TOTAL = 40000
MIN_RAPID_MOVE = 0.7
MIN_SHORT_LIQUIDATION_USD = 20000
MIN_SCORE_TO_ALERT = 3
BASE_URL = "https://api.cryptometer.io"

# Test mesajı açık/kapalı
SEND_TEST_MESSAGE = True

# ==========================================
# YARDIMCI SINIF
# ==========================================
class APIError(Exception):
    pass


# ==========================================
# API İŞLEMLERİ
# ==========================================
def api_get(path: str, params: Dict) -> Dict:
    params = dict(params)
    params["api_key"] = CRYPTOMETER_API_KEY
    url = f"{BASE_URL}{path}"

    r = requests.get(url, params=params, timeout=20)
    r.raise_for_status()
    data = r.json()

    if isinstance(data, dict) and str(data.get("error", "false")).lower() == "true":
        raise APIError(f"API hata döndürdü: {path} -> {data}")
    return data


def send_telegram(text: str) -> None:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        print(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }
    r = requests.post(url, json=payload, timeout=15)
    print("Telegram status:", r.status_code)
    print("Telegram response:", r.text[:500])


def get_rapid_movements() -> List[Dict]:
    data = api_get("/rapid-movements/", {})
    return data.get("data", []) or []


def get_volume_flow() -> Dict:
    data = api_get("/volume-flow/", {"timeframe": TIMEFRAME})
    return data.get("data", {}) or {}


def get_large_trades_activity() -> List[Dict]:
    data = api_get("/large-trades-activity/", {"e": EXCHANGE_SPOT})
    return data.get("data", []) or []


def get_liquidations(symbol: str) -> Dict:
    data = api_get("/liquidation-data-v2/", {"symbol": symbol.lower()})
    rows = data.get("data", []) or []
    return rows[0] if rows else {}


def get_live_trades(pair: str) -> Optional[Dict]:
    data = api_get("/live-trades/", {"e": EXCHANGE_SPOT, "pair": pair.lower()})
    rows = data.get("data", []) or []
    return rows[0] if rows else None


# ==========================================
# NORMALİZE / ADAY SEÇİMİ
# ==========================================
def normalize_symbol_from_pair(pair: str) -> str:
    return pair.split("-")[0].upper().strip()


def normalize_pair_for_spot(symbol: str) -> str:
    return f"{symbol.upper()}-USDT"


def extract_candidate_symbols(movers: List[Dict]) -> List[Tuple[str, Dict]]:
    candidates: List[Tuple[str, Dict]] = []
    seen = set()

    for row in movers:
        pair = str(row.get("pair", "")).upper()
        if not pair.endswith("-USDT"):
            continue

        symbol = normalize_symbol_from_pair(pair)
        if symbol in seen:
            continue

        seen.add(symbol)
        candidates.append((symbol, row))

        if len(candidates) >= TOP_CANDIDATES:
            break

    return candidates


# ==========================================
# ANALİZ FONKSİYONLARI
# ==========================================
def volume_flow_has_symbol(symbol: str, vf: Dict) -> Tuple[bool, float]:
    net = 0.0
    for row in vf.get("netflow", []) or []:
        to_symbol = str(row.get("to", "")).upper()
        if to_symbol == symbol.upper():
            net += float(row.get("volume", 0) or 0)

    return net >= MIN_NETFLOW_USD, net


def summarize_large_trade_bias(symbol: str, rows: List[Dict]) -> Tuple[bool, float, int, int]:
    buy_total = 0.0
    buy_count = 0
    sell_count = 0
    target_pair = normalize_pair_for_spot(symbol)

    for row in rows:
        pair = str(row.get("pair", "")).upper()
        side = str(row.get("side", "")).upper()
        total = float(row.get("total", 0) or 0)

        if pair != target_pair:
            continue

        if side == "BUY" and total >= MIN_LARGE_TRADE_TOTAL:
            buy_total += total
            buy_count += 1
        elif side == "SELL" and total >= MIN_LARGE_TRADE_TOTAL:
            sell_count += 1

    ok = buy_count >= 1 and buy_count >= sell_count
    return ok, buy_total, buy_count, sell_count


def liquidation_short_pressure(liq_row: Dict) -> Tuple[bool, float, float]:
    shorts = 0.0
    longs = 0.0

    for _, values in liq_row.items():
        if isinstance(values, dict):
            shorts += float(values.get("shorts", 0) or 0)
            longs += float(values.get("longs", 0) or 0)

    ok = shorts >= MIN_SHORT_LIQUIDATION_USD and shorts >= longs
    return ok, shorts, longs


def live_trade_buy_bias(live: Optional[Dict]) -> Tuple[bool, float, float]:
    if not live:
        return False, 0.0, 0.0

    row = live.get("15m") or live.get("30m") or live.get("1h") or {}
    buy_q = float(row.get("buy_quantity", 0) or 0)
    sell_q = float(row.get("sell_quantity", 0) or 0)
    return buy_q > sell_q, buy_q, sell_q


def build_signal(symbol: str, mover: Dict, vf: Dict, large_trades: List[Dict]) -> Optional[str]:
    move_side = str(mover.get("side", "")).upper()
    move_change = float(mover.get("change_detected", 0) or 0)

    # Daha fazla sinyal için sadece PUMP değil, güçlü yükselişleri de kabul ediyoruz
    if move_change < MIN_RAPID_MOVE:
        return None

    vf_ok, netflow = volume_flow_has_symbol(symbol, vf)
    lt_ok, buy_total, buy_count, sell_count = summarize_large_trade_bias(symbol, large_trades)
    liq_ok, shorts, longs = liquidation_short_pressure(get_liquidations(symbol))
    live_ok, buy_q, sell_q = live_trade_buy_bias(get_live_trades(normalize_pair_for_spot(symbol)))

    score = 0
    reasons = []

    # PRO MOD 1: hızlı hareket
    score += 1
    reasons.append(f"Rapid move: %{move_change:.2f} | Side: {move_side or 'N/A'}")

    # PRO MOD 2: net para akışı
    if vf_ok:
        score += 1
        reasons.append(f"Net flow güçlü: ${netflow:,.0f}")

    # PRO MOD 3: büyük alım baskısı
    if lt_ok:
        score += 1
        reasons.append(f"Whale/Büyük alımlar: {buy_count} adet / ${buy_total:,.0f}")
    elif sell_count > buy_count and sell_count > 0:
        reasons.append(f"Dikkat: büyük satış sayısı {sell_count}")

    # PRO MOD 4: short liquidation baskısı
    if liq_ok:
        score += 1
        reasons.append(f"Short liquidation baskısı: ${shorts:,.0f} > long ${longs:,.0f}")

    # PRO MOD 5: canlı alım baskısı
    if live_ok:
        score += 1
        reasons.append(f"Canlı alım baskısı: {buy_q:,.2f} > {sell_q:,.2f}")
    else:
        reasons.append(f"Canlı denge/zayıf alım: {buy_q:,.2f} / {sell_q:,.2f}")

    if score < MIN_SCORE_TO_ALERT:
        return None

    tv_pair = f"BINANCE:{symbol}USDT"
    msg = (
        f"🚀 PUMP / MOMENTUM ADAYI: {symbol}
"
        f"Skor: {score}/5
"
        + "
".join(f"• {r}" for r in reasons)
        + f"

TradingView: {tv_pair}
"
        f"Risk notu: işlemi onaysız açma. Grafik, hacim ve destek/direnç kontrol et.
"
        f"Kâr alma fikri: %3 / %5 / %8"
    )
    return msg


# ==========================================
# ANA ÇALIŞMA
# ==========================================
def run_once() -> None:
    if not CRYPTOMETER_API_KEY:
        raise ValueError("CRYPTOMETER_API_KEY eksik.")

    # Test mesajı
    if SEND_TEST_MESSAGE:
        send_telegram("✅ GitHub bot çalıştı. Tarama başlıyor...")

    movers = get_rapid_movements()
    vf = get_volume_flow()
    large_trades = get_large_trades_activity()
    candidates = extract_candidate_symbols(movers)

    print(f"Aday coin sayısı: {len(candidates)}")

    found = 0
    for symbol, mover in candidates:
        try:
            signal = build_signal(symbol, mover, vf, large_trades)
        except Exception as e:
            print(f"{symbol} analiz hatası: {e}")
            continue

        if signal:
            found += 1
            print(f"Sinyal bulundu: {symbol}")
            send_telegram(signal)
        else:
            print(f"Pas geçildi: {symbol}")

    if found == 0:
        send_telegram("ℹ️ Bot çalıştı ama bu turda uygun sinyal bulunamadı.")
        print("Uygun sinyal bulunamadı.")


if __name__ == "__main__":
    run_once()
