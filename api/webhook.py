import os
from fastapi import FastAPI, Request
from mangum import Mangum
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters
import asyncpg

TOKEN = os.environ["BOT_TOKEN"]
DATABASE_URL = os.environ["DATABASE_URL"]

app = FastAPI()
bot_app = ApplicationBuilder().token(TOKEN).build()
db_pool = None

async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, ssl="require")
    return db_pool

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot is live!")

async def track(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO messages(user_id, content) VALUES($1,$2)",
            update.effective_user.id,
            update.message.text
        )
    await update.message.reply_text("Message recorded!")

bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track))

@app.post("/api/webhook")
async def webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, bot_app.bot)
    await bot_app.update_queue.put(update)
    await bot_app.process_update(update)
    return {"ok": True}

handler = Mangum(app)
