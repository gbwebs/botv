# bot/telegram_bot.py
import os
import logging
from telegram import Update, MessageEntity
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
from db.database import get_connection
import asyncpg

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ----------------------
# CONSTANTS
# ----------------------
AD_WORDS = {"ad", "all done", "done", "dn"}
EXCLUDED_USERS = {"aditiraaaj", "Oyepriyankasun1"}

# ----------------------
# TABLE CREATION
# ----------------------
async def create_tables():
    conn = await get_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS participants (
            chat_id BIGINT NOT NULL,
            user_id BIGINT NOT NULL,
            srno INTEGER NOT NULL,
            name TEXT,
            username TEXT,
            x_username TEXT,
            link_count INTEGER DEFAULT 0,
            ad_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'unsafe',
            PRIMARY KEY (chat_id, user_id)
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            chat_id BIGINT PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            tracking_enabled BOOLEAN NOT NULL DEFAULT FALSE
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS links (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            text TEXT,
            message_id BIGINT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS ad_messages (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            username TEXT,
            message TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    await conn.close()
    logger.info("✅ All tables ensured")

# ----------------------
# UTILITY
# ----------------------
async def is_admin(update: Update) -> bool:
    try:
        chat = update.effective_chat
        if not update.message:
            return False
        user_id = update.message.from_user.id
        admins = await chat.get_administrators()
        return any(admin.user.id == user_id for admin in admins)
    except Exception:
        logger.exception("is_admin check failed")
        return False

# ----------------------
# COMMAND HANDLERS
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Bot started!\nUse /open to start a session.")

async def open_session(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized")
        return
    
    conn = await get_connection()
    chat_id = update.effective_chat.id
    
    await conn.execute("DELETE FROM participants WHERE chat_id=$1", chat_id)
    await conn.execute(
        "INSERT INTO sessions(chat_id, started_at, tracking_enabled) "
        "VALUES($1, now(), false) "
        "ON CONFLICT (chat_id) DO UPDATE SET started_at=now(), tracking_enabled=false",
        chat_id
    )
    await conn.close()
    await update.message.reply_text("🆕 New session started ✅ Share your post link 🖇️")

# ----------------------
# MESSAGE HANDLERS
# ----------------------
async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.message.from_user
    chat_id = update.effective_chat.id
    user_id = user.id
    username = user.username or "NoUsername"

    if username in EXCLUDED_USERS:
        return

    found_url = None
    if update.message.entities:
        for entity in update.message.entities:
            if entity.type in (MessageEntity.URL, MessageEntity.TEXT_LINK):
                found_url = getattr(entity, "url", None) or update.message.text[entity.offset:entity.offset+entity.length]
                if found_url:
                    break
    if not found_url:
        return

    x_username = None
    if "twitter.com/" in found_url or "x.com/" in found_url:
        try:
            after = found_url.split("twitter.com/")[-1].split("x.com/")[-1]
            x_username = after.split("/")[0].split("?")[0]
        except Exception:
            x_username = "Unknown"

    conn = await get_connection()
    existing = await conn.fetchrow(
        "SELECT srno, link_count FROM participants WHERE chat_id=$1 AND user_id=$2",
        chat_id, user_id
    )
    if existing:
        await conn.execute(
            "UPDATE participants SET link_count=$1 WHERE chat_id=$2 AND user_id=$3",
            existing["link_count"] + 1, chat_id, user_id
        )
    else:
        srno = await conn.fetchval("SELECT COALESCE(MAX(srno),0)+1 FROM participants WHERE chat_id=$1", chat_id)
        await conn.execute(
            "INSERT INTO participants(chat_id,user_id,srno,name,username,x_username,link_count) "
            "VALUES($1,$2,$3,$4,$5,$6,$7)",
            chat_id, user_id, srno, user.full_name, username, x_username, 1
        )
    await conn.close()
    await update.message.reply_text("🔗 Link recorded!")

async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or update.message.caption or ""
    user = update.message.from_user

    if text.lower().strip() in AD_WORDS:
        conn = await get_connection()
        chat_id = update.effective_chat.id
        user_id = user.id

        existing = await conn.fetchrow(
            "SELECT ad_count FROM participants WHERE chat_id=$1 AND user_id=$2",
            chat_id, user_id
        )
        if existing:
            await conn.execute(
                "UPDATE participants SET ad_count=$1 WHERE chat_id=$2 AND user_id=$3",
                existing["ad_count"] + 1, chat_id, user_id
            )
        else:
            await conn.execute(
                "INSERT INTO participants(chat_id,user_id,name,username,ad_count) "
                "VALUES($1,$2,$3,$4,$5)",
                chat_id, user_id, user.full_name, user.username or "NoUsername", 1
            )
        await conn.close()
        await update.message.reply_text("✅ Ad recorded for you!")
    else:
        await update.message.reply_text("ℹ️ Send 'done' when you complete an ad.")

# ----------------------
# BUILD BOT
# ----------------------
def build_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("open", open_session))

    # Message handlers
    app.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), count_links))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, count_ad_messages))
    app.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO | filters.Document.ALL, count_ad_messages))

    return app
