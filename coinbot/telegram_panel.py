from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import json

BOT_TOKEN = "BURAYA_TOKEN"

SIGNAL_FILE = "signal_history.json"


def load_signals():
    try:
        with open(SIGNAL_FILE, "r") as f:
            return json.load(f)
    except:
        return []


def menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📡 Son Sinyaller", callback_data="signals")],
        [InlineKeyboardButton("📊 Performans", callback_data="stats")]
    ])


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 Crypto Panel\n\nSeçim yap:",
        reply_markup=menu()
    )


async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = load_signals()

    if query.data == "signals":
        text = "📡 SON SİNYALLER\n\n"

        for s in data[-5:]:
            text += f"{s['symbol']} | Skor: {s['score']}\n"

    elif query.data == "stats":
        total = len(data)
        wins = len([x for x in data if x.get("tp1")])
        text = f"📊 Toplam: {total}\n"

    await query.edit_message_text(text, reply_markup=menu())


def run():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(buttons))

    app.run_polling()


if __name__ == "__main__":
    run()
