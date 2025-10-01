import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from db.database import get_connection

BOT_TOKEN = os.getenv("BOT_TOKEN")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot started!")

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    text = update.message.text

    # Store message in PostgreSQL
    conn = await get_connection()
    await conn.execute(
        "INSERT INTO messages(user_id, username, text) VALUES($1, $2, $3)",
        user.id, user.username, text
    )
    await conn.close()

    await update.message.reply_text("Message recorded!")

def build_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_message))

    return app
