import os
import requests

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram bilgileri eksik.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }

    response = requests.post(url, data=data, timeout=20)
    print("Status:", response.status_code)
    print("Response:", response.text)

if __name__ == "__main__":
    print("Bot çalıştı")
    send_telegram_message("✅ GitHub bot çalıştı. Test mesajı başarılı.")
