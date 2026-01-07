# bot/telegram_bot.py
import os
import re
import logging
from telegram import Update, MessageEntity
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
)
from db.database import get_connection

BOT_TOKEN = os.getenv("BOT_TOKEN")

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

AD_WORDS = {"ad", "all done", "done", "dn", "alldone"}
EXCLUDED_USERS = {
    "OMEGA_908","Mehunnaa","hectorthisside",
    "terakyalenadena","ShanayaVerse","Anvec14"
}

OPEN_TITLE = "VERIFIED LIKE GC [OPEN]"
CLOSED_TITLE = "VERIFIED LIKE GC [CLOSED]"

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
            tracking_enabled BOOLEAN NOT NULL DEFAULT FALSE,
            original_title TEXT
        )
    """)

    await conn.close()

# ----------------------
# UTIL
# ----------------------
async def is_admin(update: Update) -> bool:
    try:
        chat = update.effective_chat
        user_id = update.effective_user.id
        admins = await chat.get_administrators()
        return any(a.user.id == user_id for a in admins)
    except Exception:
        return False

async def get_next_srno(conn, chat_id):
    return await conn.fetchval(
        "SELECT COALESCE(MAX(srno),0)+1 FROM participants WHERE chat_id=$1",
        chat_id
    )

# ----------------------
# COMMANDS
# ----------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_sticker(
            "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        )
        return

    chat = update.effective_chat
    conn = await get_connection()

    await conn.execute("DELETE FROM participants WHERE chat_id=$1", chat.id)

    await conn.execute("""
        INSERT INTO sessions (chat_id, tracking_enabled, original_title)
        VALUES ($1, FALSE, $2)
        ON CONFLICT (chat_id)
        DO UPDATE SET tracking_enabled=FALSE
    """, chat.id, chat.title)

    await conn.close()

    try:
        await context.bot.set_chat_title(chat.id, OPEN_TITLE)
    except Exception:
        pass

    await update.message.reply_text("🚀 Session Activated\n\n🔗 Send your links")

async def start_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    chat = update.effective_chat
    conn = await get_connection()

    await conn.execute(
        "UPDATE sessions SET tracking_enabled=TRUE WHERE chat_id=$1",
        chat.id
    )
    await conn.close()

    try:
        await context.bot.set_chat_title(chat.id, CLOSED_TITLE)
    except Exception:
        pass

    await update.message.reply_text("🔒 Ad tracking started\nSend `done` after task")

async def stop_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    conn = await get_connection()
    await conn.execute(
        "UPDATE sessions SET tracking_enabled=FALSE WHERE chat_id=$1",
        update.effective_chat.id
    )
    await conn.close()

    await update.message.reply_text("🛑 Ad tracking stopped")

async def show_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    conn = await get_connection()
    rows = await conn.fetch("""
        SELECT srno, username, x_username
        FROM participants
        WHERE chat_id=$1 AND status='unsafe'
        ORDER BY srno
    """, update.effective_chat.id)
    await conn.close()

    if not rows:
        await update.message.reply_text("✅ All users safe")
        return

    msg = "⚠️ Unsafe Users\n\n"
    for r in rows:
        msg += f"{r['srno']}. @{r['username']} | X: @{r['x_username']}\n"

    await update.message.reply_text(msg)

async def show_link_counts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        return

    conn = await get_connection()
    rows = await conn.fetch("""
        SELECT username, link_count
        FROM participants
        WHERE chat_id=$1 AND link_count>1
        ORDER BY link_count DESC
    """, update.effective_chat.id)
    await conn.close()

    if not rows:
        await update.message.reply_text("No multiple links")
        return

    msg = "📊 Link Report\n\n"
    for r in rows:
        msg += f"@{r['username']} → {r['link_count']}\n"

    await update.message.reply_text(msg)

# ----------------------
# MESSAGE HANDLERS
# ----------------------
async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    user = update.effective_user
    if user.username in EXCLUDED_USERS:
        return

    chat_id = update.effective_chat.id
    text = update.message.text or ""

    url = None
    if update.message.entities:
        for e in update.message.entities:
            if e.type in (MessageEntity.URL, MessageEntity.TEXT_LINK):
                url = e.url or text[e.offset:e.offset+e.length]
                break
    if not url:
        return

    x_username = None
    if "twitter.com/" in url or "x.com/" in url:
        x_username = url.split("/")[-1].split("?")[0]

    conn = await get_connection()
    row = await conn.fetchrow(
        "SELECT * FROM participants WHERE chat_id=$1 AND user_id=$2",
        chat_id, user.id
    )

    if row:
        await conn.execute("""
            UPDATE participants
            SET link_count=link_count+1,
                x_username=COALESCE($1,x_username),
                status='unsafe'
            WHERE chat_id=$2 AND user_id=$3
        """, x_username, chat_id, user.id)
    else:
        srno = await get_next_srno(conn, chat_id)
        await conn.execute("""
            INSERT INTO participants
            (chat_id,user_id,srno,name,username,x_username,link_count)
            VALUES ($1,$2,$3,$4,$5,$6,1)
        """, chat_id, user.id, srno, user.full_name, user.username, x_username)

    await conn.close()

async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    chat_id = update.effective_chat.id
    text = (update.message.text or update.message.caption or "").lower()

    conn = await get_connection()
    session = await conn.fetchrow(
        "SELECT tracking_enabled FROM sessions WHERE chat_id=$1",
        chat_id
    )

    if not session or not session["tracking_enabled"]:
        await conn.close()
        return

    if not any(re.search(rf"\b{w}\b", text) for w in AD_WORDS):
        await conn.close()
        return

    await conn.execute("""
        UPDATE participants
        SET ad_count=ad_count+1, status='safe'
        WHERE chat_id=$1 AND user_id=$2
    """, chat_id, update.effective_user.id)

    await conn.close()
    await update.message.reply_text("✅ Ad recorded")

# ----------------------
# BUILD BOT
# ----------------------
def build_bot():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("start_ad", start_ad))
    app.add_handler(CommandHandler("stop_ad", stop_ad))
    app.add_handler(CommandHandler("count", show_link_counts))
    app.add_handler(CommandHandler("unsafe", show_unsafe_users))

    app.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), count_links))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO, count_ad_messages))

    return app
