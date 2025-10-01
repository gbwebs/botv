import os
import asyncio
from fastapi import FastAPI, Request
from mangum import Mangum
from telegram import Update, Bot
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
import asyncpg

# ------------------------------
# Environment variables
# ------------------------------
TOKEN = os.environ["BOT_TOKEN"]  # Telegram bot token
DATABASE_URL = os.environ["DATABASE_URL"]  # PostgreSQL URL

# ------------------------------
# FastAPI app
# ------------------------------
app = FastAPI()

# ------------------------------
# Telegram Bot
# ------------------------------
bot_app = ApplicationBuilder().token(TOKEN).build()

# ------------------------------
# Database pool (global for serverless)
# ------------------------------
db_pool = None

async def get_pool():
    global db_pool
    if db_pool is None:
        db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, ssl="require")
    return db_pool

# ------------------------------
# Bot command handlers
# ------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO users (id, username) 
            VALUES ($1, $2) 
            ON CONFLICT (id) DO NOTHING
        """, user.id, user.username)
    await update.message.reply_text(f"Hello {user.first_name}! Bot is active.")

async def track_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            INSERT INTO messages (user_id, content) 
            VALUES ($1, $2)
        """, user.id, text)
    # Optional reply
    await update.message.reply_text("Message recorded!")

# Register handlers
bot_app.add_handler(CommandHandler("start", start))
bot_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_message))

# ------------------------------
# Webhook endpoint
# ------------------------------
@app.post("/api/webhook")
async def telegram_webhook(req: Request):
    """Receive Telegram updates via webhook"""
    update_data = await req.json()
    update = Update.de_json(update_data, bot_app.bot)
    await bot_app.update_queue.put(update)
    await bot_app.process_update(update)  # handle immediately
    return {"ok": True}

# ------------------------------
# Mangum handler for Vercel
# ------------------------------
handler = Mangum(app)

# ------------------------------
# Optional: initialize DB tables (run once)
# ------------------------------
async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id BIGINT PRIMARY KEY,
                username TEXT
            );
        """)
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id SERIAL PRIMARY KEY,
                user_id BIGINT REFERENCES users(id),
                content TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)

# Initialize DB on cold start
asyncio.run(init_db())
