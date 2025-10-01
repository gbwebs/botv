# api/webhook.py
import os
import asyncio
import logging
import re
from datetime import timedelta
from typing import Optional

import asyncpg
from telegram import Update, Chat, ChatPermissions, MessageEntity
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from mangum import Mangum

# Load env
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Words & excluded users
AD_WORDS = {"ad", "all done", "AD", "all dn", "alldone", "done", "dn"}
EXCLUDED_USERS = {"aditiraaaj", "Oyepriyankasun1"}

# ---------- DB helpers ----------
async def create_pool():
    return await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, ssl="require")

async def create_table(pool):
    async with pool.acquire() as conn:
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

# ---------- Utility functions ----------
async def is_admin(update: Update) -> bool:
    try:
        chat = update.effective_chat
        if not update.message:
            return False
        user_id = update.message.from_user.id
        admins = await chat.get_administrators()
        return any(admin.user.id == user_id for admin in admins)
    except Exception:
        return False

async def get_session(pool, chat_id: int) -> Optional[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetchrow("SELECT * FROM sessions WHERE chat_id=$1", chat_id)

async def set_session_started(pool, chat_id: int):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions(chat_id, started_at, tracking_enabled) VALUES($1, now(), false) "
            "ON CONFLICT (chat_id) DO UPDATE SET started_at = now(), tracking_enabled = false",
            chat_id,
        )

async def set_tracking(pool, chat_id: int, enabled: bool):
    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO sessions(chat_id, started_at, tracking_enabled) VALUES($1, now(), $2) "
            "ON CONFLICT (chat_id) DO UPDATE SET tracking_enabled = $2",
            chat_id,
            enabled,
        )

async def reset_participants_for_chat(pool, chat_id: int):
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM participants WHERE chat_id = $1", chat_id)

async def upsert_participant(pool, chat_id: int, user_id: int, name: str, username: str,
                             x_username: Optional[str] = None, inc_link: int = 0, inc_ad: int = 0,
                             make_safe: Optional[bool] = None):
    async with pool.acquire() as conn:
        async with conn.transaction():
            existing = await conn.fetchrow(
                "SELECT srno, link_count, ad_count, x_username, status FROM participants WHERE chat_id=$1 AND user_id=$2 FOR UPDATE",
                chat_id, user_id
            )
            if existing is None:
                srno = await conn.fetchval("SELECT COALESCE(MAX(srno),0)+1 FROM participants WHERE chat_id=$1", chat_id)
                status = "safe" if make_safe else "unsafe"
                await conn.execute(
                    "INSERT INTO participants (chat_id,user_id,srno,name,username,x_username,link_count,ad_count,status) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    chat_id, user_id, srno, name, username, x_username, inc_link, inc_ad, status
                )
            else:
                new_link = existing["link_count"] + inc_link
                new_ad = existing["ad_count"] + inc_ad
                new_x = x_username or existing["x_username"]
                new_status = existing["status"]
                if make_safe:
                    new_status = "safe"
                await conn.execute(
                    "UPDATE participants SET link_count=$1, ad_count=$2, x_username=$3, status=$4, name=$5, username=$6 "
                    "WHERE chat_id=$7 AND user_id=$8",
                    new_link, new_ad, new_x, new_status, name, username, chat_id, user_id
                )

# ---------- Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("Unauthorized!")
        return
    pool = context.application.bot_data["db_pool"]
    chat_id = update.effective_chat.id
    await reset_participants_for_chat(pool, chat_id)
    await set_session_started(pool, chat_id)
    await update.message.reply_text("New session started ✅")

async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    pool = context.application.bot_data["db_pool"]
    user = update.message.from_user
    chat_id = update.effective_chat.id
    user_id = user.id
    username = user.username or "No Username"
    if username in EXCLUDED_USERS:
        return
    found_url = None
    if update.message.entities:
        for e in update.message.entities:
            if e.type in ("url", "text_link"):
                if e.type == "text_link":
                    found_url = e.url
                else:
                    found_url = update.message.text[e.offset:e.offset+e.length]
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
    await upsert_participant(pool, chat_id, user_id, user.full_name, username, x_username=x_username, inc_link=1)

async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    pool = context.application.bot_data["db_pool"]
    chat_id = update.effective_chat.id
    session = await get_session(pool, chat_id)
    if not session or not session.get("tracking_enabled", False):
        return
    user = update.message.from_user
    participant = await pool.fetchrow("SELECT * FROM participants WHERE chat_id=$1 AND user_id=$2", chat_id, user.id)
    if not participant:
        return
    x_username = participant.get("x_username") or "Unknown"
    text = (update.message.text or "") + " " + (update.message.caption or "")
    ad_match = any(re.search(rf"\b{w}\b", text, re.IGNORECASE) for w in AD_WORDS)
    if ad_match:
        await upsert_participant(pool, chat_id, user.id, user.full_name, user.username, inc_ad=1, make_safe=True)
        await update.message.reply_text(f"𝕏 ID: @{x_username}")

# ---------- Vercel webhook setup ----------
app = FastAPI()
loop = asyncio.get_event_loop()
pool = loop.run_until_complete(create_pool())
loop.run_until_complete(create_table(pool))
application = Application.builder().token(BOT_TOKEN).build()
application.bot_data["db_pool"] = pool
application.add_handler(CommandHandler("open", start))
application.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), count_links))
application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, count_ad_messages))

@app.post("/api/webhook")
async def telegram_webhook(req: Request):
    data = await req.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}

handler = Mangum(app)
