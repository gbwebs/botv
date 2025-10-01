#!/usr/bin/env python3
import os
import asyncio
import logging
import traceback
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

# 1️⃣ Import dotenv
from dotenv import load_dotenv

# 2️⃣ Load environment variables from .env
load_dotenv()

# 3️⃣ Access them as before
BOT_TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

# Words to check for exact matches
AD_WORDS = {"ad", "all done", "AD", "all dn", "alldone", "done", "dn"}

# Static excluded usernames (unchanged)
EXCLUDED_USERS = { "aditiraaaj", "Oyepriyankasun1"}

# Logging
logging.basicConfig(format="%(asctime)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


# # ---------- DB helpers ----------
CREATE_SESSION_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS sessions (
    chat_id BIGINT PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    tracking_enabled BOOLEAN NOT NULL DEFAULT FALSE
);
"""

CREATE_PARTICIPANTS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS participants (
    chat_id BIGINT NOT NULL,
    user_id BIGINT NOT NULL,
    srno INTEGER NOT NULL,
    name TEXT,
    username TEXT,
    x_username TEXT,
    link_count INTEGER DEFAULT 0,
    ad_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'unsafe', -- 'unsafe' or 'safe' or 'excluded'
    PRIMARY KEY (chat_id, user_id)
);
"""

async def create_pool():
    try:
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=10, ssl="require")
        logger.info("✅ Database pool created")
        return pool
    except Exception as e:
        logger.exception("❌ Failed to create DB pool: %s", e)
        return None


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
        logger.exception("is_admin check failed")
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


async def upsert_participant(
    pool,
    chat_id: int,
    user_id: int,
    name: str,
    username: str,
    x_username: Optional[str] = None,
    inc_link: int = 0,
    inc_ad: int = 0,
    make_safe: Optional[bool] = None,
):
    """
    Insert or update a participant row. If row is new, assign srno = max(srno)+1 for that chat.
    The operation is transactional to avoid race conditions.
    """
    async with pool.acquire() as conn:
        async with conn.transaction():
            # Check if exists
            existing = await conn.fetchrow(
                "SELECT srno, link_count, ad_count, x_username, status FROM participants WHERE chat_id=$1 AND user_id=$2 FOR UPDATE",
                chat_id,
                user_id,
            )
            if existing is None:
                # New row -> calculate srno
                srno = await conn.fetchval("SELECT COALESCE(MAX(srno),0) + 1 FROM participants WHERE chat_id=$1", chat_id)
                status = "safe" if make_safe else "unsafe"
                await conn.execute(
                    "INSERT INTO participants (chat_id,user_id,srno,name,username,x_username,link_count,ad_count,status) "
                    "VALUES($1,$2,$3,$4,$5,$6,$7,$8,$9)",
                    chat_id,
                    user_id,
                    srno,
                    name,
                    username,
                    x_username,
                    inc_link,
                    inc_ad,
                    status,
                )
            else:
                new_link = existing["link_count"] + inc_link
                new_ad = existing["ad_count"] + inc_ad
                new_x = x_username or existing["x_username"]
                new_status = existing["status"]
                if make_safe:
                    new_status = "safe"
                # Update basic fields as well (name/username could change)
                await conn.execute(
                    "UPDATE participants SET link_count=$1, ad_count=$2, x_username=$3, status=$4, name=$5, username=$6 "
                    "WHERE chat_id=$7 AND user_id=$8",
                    new_link,
                    new_ad,
                    new_x,
                    new_status,
                    name,
                    username,
                    chat_id,
                    user_id,
                )


# ---------- Handlers (preserve same names & logic) ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        # Reset DB session + participants for this chat -> same semantics as original 'start'
        await reset_participants_for_chat(pool, chat_id)
        await set_session_started(pool, chat_id)

        await update.message.reply_text("New session has started ✅\n\nPlease share your post link 🖇️")
    except Exception:
        logger.exception("Error in /open (start)")
        if update.message:
            await update.message.reply_text("⚠️ Something went wrong while starting session, but bot is still running.")


async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return

        pool = context.application.bot_data["db_pool"]
        user = update.message.from_user
        chat_id = update.effective_chat.id
        user_id = user.id
        user_full_name = user.full_name
        user_username = user.username or "No Username"

        # Skip excluded usernames
        if user_username in EXCLUDED_USERS:
            return

        # Process entities (find first url or text_link)
        if not update.message.entities:
            return

        found_url = None
        for entity in update.message.entities:
            if entity.type in (MessageEntity.URL, MessageEntity.TEXT_LINK, "url", "text_link"):
                if entity.type == MessageEntity.TEXT_LINK or entity.type == "text_link":
                    found_url = entity.url  # text_link has .url
                else:
                    # entity.offset + length is safe only if text exists
                    text = update.message.text or ""
                    start = entity.offset
                    end = entity.offset + entity.length
                    found_url = text[start:end]
                if found_url:
                    break

        if not found_url:
            return

        # Try to extract X/Twitter username
        x_username = None
        if "twitter.com/" in found_url or "x.com/" in found_url:
            try:
                # robust extraction
                after = found_url.split("twitter.com/")[-1].split("x.com/")[-1]
                x_username = after.split("/")[0].split("?")[0]
            except Exception:
                x_username = "Unknown"

        # Upsert participant and increment link_count by 1
        await upsert_participant(
            pool,
            chat_id,
            user_id,
            user_full_name,
            user_username,
            x_username=x_username,
            inc_link=1,
            inc_ad=0,
            make_safe=None,
        )

        # If user not in safe and not in participants marked safe -> ensure status unsafe -> handled by upsert
    except Exception:
        logger.exception("Error in count_links")


async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not update.message:
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        # Is tracking enabled for this chat?
        session = await get_session(pool, chat_id)
        if not session or not session.get("tracking_enabled", False):
            return

        user = update.message.from_user
        user_id = user.id
        user_full_name = user.full_name
        user_username = user.username or "No Username"

        # Only proceed if participant exists
        participant = await pool.fetchrow("SELECT * FROM participants WHERE chat_id=$1 AND user_id=$2", chat_id, user_id)
        if not participant:
            # do not create new entry here (preserve your original logic)
            return

        x_username = participant.get("x_username") or "Unknown"

        message_text = update.message.text or ""
        caption_text = update.message.caption or ""
        combined_text = f"{message_text} {caption_text}".strip()

        # Check for exact word matches
        ad_match = any(re.search(rf"\b{re.escape(word)}\b", combined_text, re.IGNORECASE) for word in AD_WORDS)

        if ad_match:
            # increment ad_count and mark safe
            await upsert_participant(
                pool,
                chat_id,
                user_id,
                user_full_name,
                user_username,
                x_username=None,
                inc_link=0,
                inc_ad=1,
                make_safe=True,
            )
            # reply with stored x_username (as original)
            await update.message.reply_text(f"𝕏 ID: @{x_username}\n")
        else:
            # mark as unsafe if not already safe
            row = await pool.fetchrow("SELECT status FROM participants WHERE chat_id=$1 AND user_id=$2", chat_id, user_id)
            if row and row.get("status") != "safe":
                # leave as unsafe (or insert if not present) — original logic added user to unsafe_users
                await pool.execute(
                    "UPDATE participants SET status='unsafe' WHERE chat_id=$1 AND user_id=$2",
                    chat_id,
                    user_id,
                )
    except Exception:
        logger.exception("Error in count_ad_messages")


async def show_ad_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id
        total = await pool.fetchval("SELECT COUNT(*) FROM participants WHERE chat_id=$1 AND ad_count>0", chat_id)
        if total and total > 0:
            await update.message.reply_text(f"✅ {total} users have completed the ad task so far.")
        else:
            await update.message.reply_text("❌ No users have completed the ad task yet.")
    except Exception:
        logger.exception("Error in show_ad_completed")


async def multiple_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        total_participants = await pool.fetchval("SELECT COUNT(*) FROM participants WHERE chat_id=$1", chat_id)
        if total_participants == 0:
            await update.message.reply_text("No one shared links yet!")
            return

        # Users with multiple links
        rows = await pool.fetch(
            "SELECT srno,name,link_count FROM participants WHERE chat_id=$1 AND link_count>1 ORDER BY srno",
            chat_id,
        )
        users_with_multiple_links = [{"srno": r["srno"], "name": r["name"], "link_count": r["link_count"]} for r in rows]

        # Users with same x_username (group by x_username)
        groups = await pool.fetch(
            "SELECT x_username, array_agg(row_to_json((srno,name,username,link_count))) as users "
            "FROM participants WHERE chat_id=$1 AND x_username IS NOT NULL GROUP BY x_username HAVING COUNT(*)>1",
            chat_id,
        )

        response_text = ""
        if users_with_multiple_links:
            response_text += "multiple links:\n"
            for user in users_with_multiple_links:
                response_text += f"{user['srno']}. {user['name']} - {user['link_count']}\n"

        if groups:
            response_text += "\nsame X username:\n"
            for g in groups:
                xname = g["x_username"]
                response_text += f"X Username: @{xname}\n"
                # g["users"] is a list of json objects as text
                users = g["users"]
                for u in users:
                    # u has srno and name (as JSON)
                    try:
                        # parse structure if needed
                        response_text += f"{u['srno']}. {u['name']} "
                    except Exception:
                        # fallback
                        response_text += f"{u} "

        if not response_text:
            response_text = "No multiple links or users with the same X username yet."

        await update.message.reply_text(response_text)
    except Exception:
        logger.exception("Error in multiple_links")


async def show_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        rows = await pool.fetch("SELECT srno,name,username FROM participants WHERE chat_id=$1 AND status='unsafe' ORDER BY srno", chat_id)
        if not rows:
            await update.message.reply_text("All safe!")
            return

        text = "\n".join(f"{r['srno']}. {r['name']} (@{r['username']})" for r in rows)
        await update.message.reply_text(f"Unsafe list:\n{text}")
    except Exception:
        logger.exception("Error in show_unsafe_users")


async def show_link_counts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        total_users = await pool.fetchval("SELECT COUNT(*) FROM participants WHERE chat_id=$1 AND link_count>0", chat_id)
        if not total_users:
            await update.message.reply_text("No one shared link!")
            return

        await update.message.reply_text(f"Total shared links: {total_users}")
    except Exception:
        logger.exception("Error in show_link_counts")


async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("🚫 Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        rows = await pool.fetch("SELECT srno,name,x_username FROM participants WHERE chat_id=$1 ORDER BY srno", chat_id)
        if not rows:
            await update.message.reply_text("🔴 No users found!")
            return

        user_list_text = "*List*:\n\n"
        batch_text = ""
        counter = 0
        for r in rows:
            x_display = f"✖️ @{r['x_username']}" if r.get("x_username") else "✖️ Unknown"
            batch_text += f"{r['srno']}. {r['name']} - {x_display}\n"
            counter += 1
            if counter % 80 == 0:
                await update.message.reply_text(batch_text)
                batch_text = ""
        if batch_text:
            await update.message.reply_text(batch_text)
    except Exception:
        logger.exception("Error in user_list")


async def show_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id

        rows = await pool.fetch("SELECT srno,name,ad_count FROM participants WHERE chat_id=$1 ORDER BY srno", chat_id)
        if not rows:
            await update.message.reply_text("❌ No users found in the list.")
            return

        checklist = []
        for r in rows:
            ad_completed = "✅" if r["ad_count"] and r["ad_count"] > 0 else "❌"
            checklist.append(f"{r['srno']}. {r['name']} - {ad_completed}")

        await update.message.reply_text("📋 Checklist:\n" + "\n".join(checklist))
    except Exception:
        logger.exception("Error in show_checklist")


async def clear_counts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat = update.effective_chat

        if chat.type in [Chat.GROUP, Chat.SUPERGROUP]:
            await reset_participants_for_chat(pool, chat.id)
            await update.message.reply_text("Cleared all!")
        else:
            user = update.message.from_user
            await pool.execute("DELETE FROM participants WHERE chat_id=$1 AND user_id=$2", chat.id, user.id)
            await update.message.reply_text(f"All data for {user.full_name} has been cleared!")
    except Exception:
        logger.exception("Error in clear_counts")


async def _find_user_id_by_username(pool, chat_id: int, username: str) -> Optional[int]:
    row = await pool.fetchrow("SELECT user_id, name FROM participants WHERE chat_id=$1 AND username=$2", chat_id, username)
    if row:
        return row["user_id"], row["name"]
    return None, None


async def mute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        if len(context.args) < 1:
            await update.message.reply_text("Usage: /muteuser @username (e.g., /muteuser @username)")
            return

        username = context.args[0]
        if not username.startswith("@"):
            await update.message.reply_text("Invalid username")
            return
        username_clean = username[1:]

        pool = context.application.bot_data["db_pool"]
        chat = update.effective_chat

        target_user_id, target_user_name = await _find_user_id_by_username(pool, chat.id, username_clean)
        if not target_user_id:
            await update.message.reply_text(f"User {username} not found")
            return

        bot_member = await chat.get_member(context.bot.id)
        if not bot_member.can_restrict_members:
            await update.message.reply_text("I need 'Manage Members' permissions to mute users.")
            return

        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=None,
        )
        await update.message.reply_text(f"Muted {target_user_name} ({username}) indefinitely.")
    except Exception:
        logger.exception("Error in mute_user")


async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        if len(context.args) != 1:
            await update.message.reply_text("Usage: /unmuteuser @username (e.g., /unmuteuser @username)")
            return

        username = context.args[0]
        if not username.startswith("@"):
            await update.message.reply_text("Invalid username")
            return
        username_clean = username[1:]

        pool = context.application.bot_data["db_pool"]
        chat = update.effective_chat

        target_user_id, target_user_name = await _find_user_id_by_username(pool, chat.id, username_clean)
        if not target_user_id:
            await update.message.reply_text(f"User {username} not found.")
            return

        bot_member = await chat.get_member(context.bot.id)
        if not bot_member.can_restrict_members:
            await update.message.reply_text("I need 'Manage Members' permissions to unmute users.")
            return

        await context.bot.restrict_chat_member(
            chat_id=chat.id,
            user_id=target_user_id,
            permissions=ChatPermissions(can_send_messages=True),
        )
        await update.message.reply_text(f"Unmuted {target_user_name} ({username}).")
    except Exception:
        logger.exception("Error in unmute_user")


async def start_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id
        await set_tracking(pool, chat_id, True)
        await update.message.reply_text("Ad tracking enabled ✅\nPlease drop the ad along with your username (the ID you used to complete the task).")
    except Exception:
        logger.exception("Error in start_ad")


async def stop_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        pool = context.application.bot_data["db_pool"]
        chat_id = update.effective_chat.id
        await set_tracking(pool, chat_id, False)
        await update.message.reply_text("Ad tracking has been stopped.")
    except Exception:
        logger.exception("Error in stop_ad")


async def rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            await update.message.reply_text("Unauthorized access attempt!")
            return

        rules_text = """
Participation Guidelines//Rules

1. Follow These Accounts
•Personal Accounts:
•Priyanka: x.com/oyepriyankasun
•Aditi: x.com/aditiraaaj
•Pihu: x.com/oyepriyankasun1

TL Accounts:
• x.com/aditiraaaj1
• x.com/aditiraaaj2

2. Tweet Sharing Rules
Remove any text after the "?" in tweet links (e.g., ?lang=en).
•Each participant can share only one tweet link.

3. Telegram Profile Requirements
•Your Telegram username must be visible in settings.
•Your Telegram name must match your X (Twitter) account name.

4. Screen Recording Instructions (If Needed)
•Ensure your profile is clearly visible in the recording.
•Start recording from the timeline open to close, scrolling top to bottom.

5. Backup/Alt Account Confirmation
If using a backup or alt account, mention your @username along with "done" after following the required accounts.

X (formerly Twitter): x.com/aditiraaaj
"""
        await update.message.reply_text(rules_text)
    except Exception:
        logger.exception("Error in rules")


async def mute_all_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if not await is_admin(update):
            STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
            await update.message.reply_sticker(STICKER_ID)
            return

        if len(context.args) < 1:
            await update.message.reply_text("Usage: /muteall duration (e.g., /muteall 5h)")
            return

        duration = context.args[0]
        duration_match = re.match(r"(\d+)([smhd])$", duration)
        if not duration_match:
            await update.message.reply_text("Invalid duration. Use format like 5m (minutes), 2h (hours), or 1d (days).")
            return

        time_value = int(duration_match.group(1))
        time_unit = duration_match.group(2)
        if time_unit == "s":
            mute_duration = timedelta(seconds=time_value)
        elif time_unit == "m":
            mute_duration = timedelta(minutes=time_value)
        elif time_unit == "h":
            mute_duration = timedelta(hours=time_value)
        elif time_unit == "d":
            mute_duration = timedelta(days=time_value)

        pool = context.application.bot_data["db_pool"]
        chat = update.effective_chat

        rows = await pool.fetch("SELECT user_id,name,username FROM participants WHERE chat_id=$1 AND status='unsafe'", chat.id)
        if not rows:
            await update.message.reply_text("No users in the unsafe list to mute.")
            return

        bot_member = await chat.get_member(context.bot.id)
        if not bot_member.can_restrict_members:
            await update.message.reply_text("I need 'Manage Members' permissions to mute users.")
            return

        muted_users = []
        failed_users = []
        for r in rows:
            try:
                await context.bot.restrict_chat_member(
                    chat_id=chat.id,
                    user_id=r["user_id"],
                    permissions=ChatPermissions(can_send_messages=False),
                    until_date=update.message.date + mute_duration,
                )
                muted_users.append(f"{r['name']} (@{r['username']})")
            except Exception as e:
                failed_users.append(f"{r['name']} (@{r['username']}): {e}")

        response_message = "✅ muted the following users:\n" + "\n".join(muted_users) if muted_users else "❌ No users were muted."
        if failed_users:
            response_message += "\n\nFailed:\n" + "\n".join(failed_users)
        await update.message.reply_text(response_message)
    except Exception:
        logger.exception("Error in mute_all_unsafe_users")


# ---------- Global error handler ----------
async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Unhandled exception", exc_info=context.error)
    try:
        if isinstance(update, Update) and update.message:
            await update.message.reply_text("⚠️ An internal error occurred, but the bot is still running.")
    except Exception:
        logger.exception("Failed to send error message to chat")

async def create_table(pool):
    async with pool.acquire() as conn:
         # Users table
        await conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            telegram_id BIGINT UNIQUE,
            username TEXT,
            x_username TEXT,
            link_count INT DEFAULT 0,
            ad_count INT DEFAULT 0
        )
        """)
        logger.info("✅ Users table ready")

        # Participants table
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
        logger.info("✅ Participants table ready")

        await conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            chat_id BIGINT PRIMARY KEY,
            started_at TIMESTAMPTZ NOT NULL,
            tracking_enabled BOOLEAN NOT NULL DEFAULT FALSE
        )
        """)
        logger.info("✅ Sessions table ready")

if __name__ == "__main__":
    # Windows-specific fix for PTB + asyncio
    if os.name == "nt":
        asyncio.set_event_loop(asyncio.ProactorEventLoop())

    loop = asyncio.get_event_loop()

    # DB setup before starting bot
    pool = loop.run_until_complete(create_pool())
    if pool:
        loop.run_until_complete(create_table(pool))

    # Build PTB application
    application = Application.builder().token(BOT_TOKEN).build()
    application.bot_data["db_pool"] = pool

    # Add your handlers here...
    # application.add_handler(...)
    application.add_handler(CommandHandler("open", start))
    application.add_handler(CommandHandler("count", show_link_counts))
    application.add_handler(CommandHandler("unsafeuser", show_unsafe_users))
    application.add_handler(CommandHandler("close2", clear_counts))
    application.add_handler(CommandHandler("mute2", mute_user))
    application.add_handler(CommandHandler("unmuteuser2", unmute_user))
    application.add_handler(CommandHandler("test", start_ad))  # New command
    application.add_handler(CommandHandler("stop_ad", stop_ad))
    application.add_handler(CommandHandler("rules2", rules))  # New rules command
    application.add_handler(CommandHandler("doublelinks", multiple_links))  # New multiple links command
    application.add_handler(CommandHandler("userlist", user_list))
    application.add_handler(CommandHandler("count_ad", show_ad_completed))
    application.add_handler(CommandHandler("testlist", show_checklist))
    application.add_handler(CommandHandler("muteall", mute_all_unsafe_users))

    application.add_handler(MessageHandler(filters.Entity("url") | filters.Entity("text_link"), count_links))
    application.add_handler(MessageHandler(filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL, count_ad_messages))

    # Run the bot (PTB manages the loop internally)
    application.run_polling(close_loop=False)

    # Cleanup DB pool after bot stops
    if pool:
        loop.run_until_complete(pool.close())
        logger.info("✅ DB pool closed")

