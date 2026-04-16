from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import json

BOT_TOKEN = "8567778990:AAFfGmVWpV8ReszFQuAtOcwGqjKRF9_H75o"
SIGNAL_FILE = "signal_history.json"


def load_signals():
    try:
        with open(SIGNAL_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Son Sinyaller", callback_data="signals")],
        [InlineKeyboardButton("📊 Performans", callback_data="stats")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Crypto Panel\n\nAşağıdan seçim yap:",
        reply_markup=menu()
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_signals()

    if query.data == "signals":
        text = "📡 Son Sinyaller\n\n"
        if not data:
            text += "Henüz kayıtlı sinyal yok."
        else:
            for s in data[-5:]:
                symbol = s.get("symbol", "-")
                score = s.get("score", "-")
                move = s.get("move_side", "-")
                text += f"{symbol} | {move} | Skor: {score}\n"

    elif query.data == "stats":
        total = len(data)
        text = (
            "📊 Performans\n\n"
            f"Toplam kayıtlı sinyal: {total}\n"
        )

    else:
        text = "Menü"

    await query.edit_message_text(text, reply_markup=menu())


def run():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))
    print("Panel bot çalışıyor...")
    app.run_polling()


if __name__ == "__main__":
    run()
