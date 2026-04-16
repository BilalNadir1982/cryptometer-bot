import os
import json
import requests
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta

CRYPTOMETER_API_KEY = os.getenv("CRYPTOMETER_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

EXCHANGE_SPOT = "binance"
TIMEFRAME = "15m"
TOP_CANDIDATES = 12
MIN_NETFLOW_USD = 150000
MIN_LARGE_TRADE_TOTAL = 50000
MIN_RAPID_MOVE = 1.0
MIN_SHORT_LIQUIDATION_USD = 25000
MIN_SCORE_TO_ALERT = 4
BASE_URL = "https://api.cryptometer.io"
SEND_TEST_MESSAGE = True

COOLDOWN_MINUTES = 60
ALERT_STATE_FILE = "alert_state.json"
SIGNAL_HISTORY_FILE = "signal_history.json"

MIN_BUY_SELL_RATIO = 1.15
MAX_SELL_COUNT_OVER_BUY = 1
REQUIRE_POSITIVE_LIVE_FLOW = True
REQUIRE_PUMP_SIDE = False

DEFAULT_STOP_PCT = 2.0
TP1_PCT = 3.0
TP2_PCT = 5.0
TP3_PCT = 8.0

# YENİ EKLENEN AYARLAR
STRONG_SCORE_MIN = 5
MEDIUM_SCORE_MIN = 4
ALLOW_WEAK_SIGNALS = False
SEND_COOLDOWN_LOG = True


class APIError(Exception):
    pass


def load_json_file(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json_file(path: str, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_alert_state() -> Dict:
    return load_json_file(ALERT_STATE_FILE, {})


def save_alert_state(state: Dict) -> None:
    save_json_file(ALERT_STATE_FILE, state)


def can_send_alert(symbol: str, state: Dict) -> bool:
    last_time_str = state.get(symbol)
    if not last_time_str:
        return True

    try:
        last_time = datetime.fromisoformat(last_time_str)
    except Exception:
        return True

    return datetime.utcnow() >= last_time + timedelta(minutes=COOLDOWN_MINUTES)


def mark_alert_sent(symbol: str, state: Dict) -> None:
    state[symbol] = datetime.utcnow().isoformat()
    save_alert_state(state)


def load_signal_history() -> List[Dict]:
    return load_json_file(SIGNAL_HISTORY_FILE, [])


def save_signal_history(history: List[Dict]) -> None:
    save_json_file(SIGNAL_HISTORY_FILE, history)


def append_signal_history(record: Dict) -> None:
    history = load_signal_history()
    history.append(record)

    max_records = 500
    if len(history) > max_records:
        history = history[-max_records:]

    save_signal_history(history)


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


def pick_entry_price(mover: Dict, live: Optional[Dict]) -> float:
    candidates = []

    for key in ["price", "last_price", "current_price", "close", "mark_price"]:
        val = mover.get(key)
        if val not in (None, ""):
            try:
                candidates.append(float(val))
            except Exception:
                pass

    if live:
        for tf in ["15m", "30m", "1h"]:
            row = live.get(tf) or {}
            for key in ["price", "last_price", "close", "mark_price"]:
                val = row.get(key)
                if val not in (None, ""):
                    try:
                        candidates.append(float(val))
                    except Exception:
                        pass

    for c in candidates:
        if c > 0:
            return c
    return 0.0


def calc_trade_levels(entry_price: float) -> Dict[str, float]:
    if entry_price <= 0:
        return {"entry": 0.0, "sl": 0.0, "tp1": 0.0, "tp2": 0.0, "tp3": 0.0}

    sl = entry_price * (1 - DEFAULT_STOP_PCT / 100)
    tp1 = entry_price * (1 + TP1_PCT / 100)
    tp2 = entry_price * (1 + TP2_PCT / 100)
    tp3 = entry_price * (1 + TP3_PCT / 100)

    return {
        "entry": entry_price,
        "sl": sl,
        "tp1": tp1,
        "tp2": tp2,
        "tp3": tp3,
    }


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

    ok = buy_count >= 1 and sell_count <= (buy_count + MAX_SELL_COUNT_OVER_BUY)
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


def live_trade_buy_bias(live: Optional[Dict]) -> Tuple[bool, float, float, float]:
    if not live:
        return False, 0.0, 0.0, 0.0

    row = live.get("15m") or live.get("30m") or live.get("1h") or {}
    buy_q = float(row.get("buy_quantity", 0) or 0)
    sell_q = float(row.get("sell_quantity", 0) or 0)
    ratio = (buy_q / sell_q) if sell_q > 0 else (999.0 if buy_q > 0 else 0.0)
    ok = buy_q > sell_q and ratio >= MIN_BUY_SELL_RATIO
    return ok, buy_q, sell_q, ratio


def smart_fake_pump_filter(
    move_side: str,
    move_change: float,
    vf_ok: bool,
    lt_ok: bool,
    liq_ok: bool,
    live_ok: bool,
    buy_count: int,
    sell_count: int,
    ratio: float,
) -> Tuple[bool, str]:
    if REQUIRE_PUMP_SIDE and move_side != "PUMP":
        return False, "PUMP tarafı değil"

    if move_change < MIN_RAPID_MOVE:
        return False, "Yeterli hızlı yükseliş yok"

    if sell_count > buy_count + MAX_SELL_COUNT_OVER_BUY:
        return False, "Büyük satış baskısı fazla"

    if REQUIRE_POSITIVE_LIVE_FLOW and not live_ok:
        return False, "Canlı alım baskısı zayıf"

    positive_signals = sum([vf_ok, lt_ok, liq_ok, live_ok])
    if positive_signals < 3:
        return False, "Onay sayısı düşük"

    if ratio and ratio < MIN_BUY_SELL_RATIO:
        return False, "Buy/Sell oranı zayıf"

    return True, "Geçti"


def classify_signal_strength(score: int) -> str:
    if score >= STRONG_SCORE_MIN:
        return "GÜÇLÜ"
    elif score >= MEDIUM_SCORE_MIN:
        return "ORTA"
    return "ZAYIF"


def build_signal(symbol: str, mover: Dict, vf: Dict, large_trades: List[Dict]) -> Optional[Tuple[str, Dict]]:
    move_side = str(mover.get("side", "")).upper()
    move_change = float(mover.get("change_detected", 0) or 0)

    vf_ok, netflow = volume_flow_has_symbol(symbol, vf)
    lt_ok, buy_total, buy_count, sell_count = summarize_large_trade_bias(symbol, large_trades)
    liq_ok, shorts, longs = liquidation_short_pressure(get_liquidations(symbol))
    live = get_live_trades(normalize_pair_for_spot(symbol))
    live_ok, buy_q, sell_q, ratio = live_trade_buy_bias(live)

    fake_ok, fake_reason = smart_fake_pump_filter(
        move_side, move_change, vf_ok, lt_ok, liq_ok, live_ok,
        buy_count, sell_count, ratio
    )
    if not fake_ok:
        print(f"{symbol} elendi -> {fake_reason}")
        return None

    score = 0
    reasons = []

    score += 1
    reasons.append(f"Rapid move: %{move_change:.2f} | Side: {move_side or 'N/A'}")

    if vf_ok:
        score += 1
        reasons.append(f"Net flow güçlü: ${netflow:,.0f}")

    if lt_ok:
        score += 1
        reasons.append(f"Whale/Büyük alımlar: {buy_count} adet / ${buy_total:,.0f}")

    if liq_ok:
        score += 1
        reasons.append(f"Short liquidation baskısı: ${shorts:,.0f} > long ${longs:,.0f}")

    if live_ok:
        score += 1
        reasons.append(f"Canlı alım baskısı: {buy_q:,.2f} > {sell_q:,.2f} | Oran: {ratio:.2f}")

    if score < MIN_SCORE_TO_ALERT:
        return None

    strength = classify_signal_strength(score)

    if strength == "ZAYIF" and not ALLOW_WEAK_SIGNALS:
        print(f"{symbol} zayıf sinyal olduğu için elendi.")
        return None

    entry_price = pick_entry_price(mover, live)
    levels = calc_trade_levels(entry_price)
    tv_pair = f"BINANCE:{symbol}USDT"

    if levels["entry"] > 0:
        level_text = (
            f"Giriş: {levels['entry']:.8f}\n"
            f"SL: {levels['sl']:.8f} (-%{DEFAULT_STOP_PCT})\n"
            f"TP1: {levels['tp1']:.8f} (+%{TP1_PCT})\n"
            f"TP2: {levels['tp2']:.8f} (+%{TP2_PCT})\n"
            f"TP3: {levels['tp3']:.8f} (+%{TP3_PCT})"
        )
    else:
        level_text = "Giriş/TP/SL hesaplanamadı: fiyat verisi yok"

    msg = (
        f"🚀 YÜKSEK İHTİMAL PUMP ADAYI: {symbol}\n"
        f"Güç: {strength}\n"
        f"Skor: {score}/5\n"
        + "\n".join(f"• {r}" for r in reasons)
        + f"\n\n{level_text}\n\n"
        f"TradingView: {tv_pair}\n"
        f"Akıllı filtre: fake pump eleme geçti ✅"
    )

    signal_data = {
        "symbol": symbol,
        "strength": strength,
        "score": score,
        "move_side": move_side,
        "move_change_pct": round(move_change, 4),
        "netflow_usd": round(netflow, 2),
        "buy_total_usd": round(buy_total, 2),
        "buy_count": buy_count,
        "sell_count": sell_count,
        "short_liq_usd": round(shorts, 2),
        "long_liq_usd": round(longs, 2),
        "buy_qty": round(buy_q, 6),
        "sell_qty": round(sell_q, 6),
        "buy_sell_ratio": round(ratio, 4),
        "entry": round(levels["entry"], 8),
        "sl": round(levels["sl"], 8),
        "tp1": round(levels["tp1"], 8),
        "tp2": round(levels["tp2"], 8),
        "tp3": round(levels["tp3"], 8),
        "tradingview": tv_pair,
        "reasons": reasons,
    }

    return msg, signal_data


def run_once() -> None:
    if not CRYPTOMETER_API_KEY:
        raise ValueError("CRYPTOMETER_API_KEY eksik.")

    if SEND_TEST_MESSAGE:
        send_telegram("✅ GitHub bot çalıştı. Akıllı filtreli tarama başlıyor...")

    movers = get_rapid_movements()
    vf = get_volume_flow()
    large_trades = get_large_trades_activity()
    candidates = extract_candidate_symbols(movers)

    print(f"Aday coin sayısı: {len(candidates)}")
    state = load_alert_state()

    found = 0
    for symbol, mover in candidates:
        try:
            result = build_signal(symbol, mover, vf, large_trades)
        except Exception as e:
            print(f"{symbol} analiz hatası: {e}")
            continue

        if result:
            signal_text, signal_data = result
            if can_send_alert(symbol, state):
                found += 1
                print(f"Sinyal gönderildi: {symbol}")
                send_telegram(signal_text)
                mark_alert_sent(symbol, state)

                history_record = {
                    "timestamp_utc": datetime.utcnow().isoformat(),
                    **signal_data,
                }
                append_signal_history(history_record)
            else:
                cooldown_text = f"⏳ Cooldown aktif: {symbol} için tekrar sinyal gönderilmedi."
                print(cooldown_text)
                if SEND_COOLDOWN_LOG:
                    send_telegram(cooldown_text)
        else:
            print(f"Pas geçildi: {symbol}")

    if found == 0:
        send_telegram("ℹ️ Bot çalıştı ama bu turda yüksek ihtimalli uygun sinyal bulunamadı.")
        print("Uygun sinyal bulunamadı.")


if __name__ == "__main__":
    run_once()
