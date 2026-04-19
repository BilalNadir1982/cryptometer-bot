import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

FUTURES_EXCHANGE_INFO_URL = "https://fapi.binance.com/fapi/v1/exchangeInfo"
FUTURES_TICKER_24H_URL = "https://fapi.binance.com/fapi/v1/ticker/24hr"

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
    try:
        r = requests.post(url, data=data, timeout=20)
        print("Telegram:", r.status_code, r.text[:200])
    except Exception as e:
        print("Telegram hata:", e)

def debug_request(name, url, params=None):
    try:
        r = SESSION.get(url, params=params, timeout=20)
        text = r.text[:800]

        msg = (
            f"DEBUG {name}\n"
            f"status={r.status_code}\n"
            f"url={r.url}\n"
            f"cevap=\n{text}"
        )
        print(msg)
        send_telegram(msg[:3500])
    except Exception as e:
        err = f"DEBUG {name} hata: {e}"
        print(err)
        send_telegram(err)

def main():
    send_telegram("✅ Futures debug testi başladı")
    debug_request("exchangeInfo", FUTURES_EXCHANGE_INFO_URL)
    debug_request("ticker24hr", FUTURES_TICKER_24H_URL)

if __name__ == "__main__":
    main()
