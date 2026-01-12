from telegram import Update, Chat, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, timedelta
import telegram
import logging
import re
import os
from db.database import  fetchrow, fetch, execute
from db.queries import clear_users_table



def escape_markdown_v2(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!?"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)


# Enable logging
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)

# Words to check for exact matches
ad_words = {"ad", "all done", "AD", "all dn", "alldone", "done"}

excluded_users = {
    "OMEGA_9082",
    "Mehunnaa11",
    "hectorthisside",
    "RealRavY",
    "Masalamoodz",
    "meethirasmalai",
    "Crystal_050",
    "terakyalenadena",
    "TumseKyaaMatlab",
    "Pandeyshanaya1",
    "ieshu07"
}


async def is_admin(update: Update) -> bool:
    chat = update.effective_chat
    user_id = update.message.from_user.id
    admins = await chat.get_administrators()
    return any(admin.user.id == user_id for admin in admins)


# =========================
# START / OPEN SESSION
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    chat_id = update.effective_chat.id
    # 🧹 Clear previous users
    await clear_users_table()

    # 🔁 Update Group Name
    try:
        await context.bot.set_chat_title(
            chat_id=chat_id,
            title="VERIFIED LIKE GC [OPEN]"
        )
    except Exception as e:
        logger.warning(f"Group title update failed: {e}")

    # 🔒 Change permissions → TEXT ONLY
    try:
        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            )
        )
    except Exception as e:
        logger.warning(f"Permission update failed: {e}")

    # 🧠 SESSION RESET (DATABASE ONLY)
    await execute(
        """
        INSERT INTO sessionsdata (chat_id, tracking_enabled, start_time, end_time)
        VALUES ($1, false, NOW(), NULL)
        ON CONFLICT (chat_id)
        DO UPDATE SET
            tracking_enabled = false,
            start_time = NOW(),
            end_time = NULL
        """,
        chat_id
    )

    # 📌 Info message
    msg = await update.message.reply_text(
        "🚀 *Session Started Successfully!*\n\n"
        "🔗 Send your links below",
        parse_mode="Markdown"
    )

    # 📌 Pin the message
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True
        )
    except Exception as e:
        logger.warning(f"Pin message failed: {e}")


# Message handler to count messages with links
# =========================
# COUNT LINKS (DB BASED)
# =========================
async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message or not update.message.entities:
        return

    user = update.message.from_user
    chat_id = update.effective_chat.id
    user_id = user.id
    full_name = user.full_name
    username = user.username or "NoUsername"

    # 🚫 Skip excluded users
    if username in excluded_users:
        return

    for entity in update.message.entities:
        if entity.type not in ("url", "text_link"):
            continue

        # 🔗 Extract URL
        url = update.message.text[entity.offset: entity.offset + entity.length]

        # 🐦 Extract X username
        x_username = None
        try:
            if "twitter.com/" in url:
                x_username = url.split("twitter.com/")[-1].split("/")[0].split("?")[0]
            elif "x.com/" in url:
                x_username = url.split("x.com/")[-1].split("/")[0].split("?")[0]
        except Exception:
            pass

        INVALID_X = {"i", "status", ""}

        if not x_username or x_username in INVALID_X:
            x_username = None

        # 🧠 UPSERT USER (LINK COUNT + X USERNAME)
        user_row = await fetchrow(
            """
            INSERT INTO users (chat_id, tg_user_id, username, full_name, x_username, link_count, status)
            VALUES ($1,$2,$3,$4,$5,1,'unsafe')
            ON CONFLICT (chat_id, tg_user_id)
            DO UPDATE SET
                link_count = users.link_count + 1,
                x_username = COALESCE(users.x_username, EXCLUDED.x_username)
            RETURNING id, link_count
            """,
            chat_id,
            user_id,
            username,
            full_name,
            x_username
        )

        # 🧾 STORE LINK
        await execute(
            "INSERT INTO links (user_id, url) VALUES ($1,$2)",
            user_row["id"],
            url
        )

        # ⚠️ ALERT: more than 1 link
        if user_row["link_count"] > 1:
            mention = f"@{username}" if user.username else full_name
            await update.message.reply_text(
                f"⚠️ Alert: {mention} shared more than one link."
            )

        break  # ✅ One link per message

async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):

    if not update.message:
        return

    chat_id = update.effective_chat.id
    user = update.message.from_user
    user_id = user.id

    # 🧠 Check if tracking is enabled
    session = await fetchrow(
        "SELECT tracking_enabled FROM sessionsdata WHERE chat_id=$1",
        chat_id
    )

    if not session or not session["tracking_enabled"]:
        return

    # 📝 Combine text + caption
    text = f"{update.message.text or ''} {update.message.caption or ''}"

    # 🔍 AD keyword match
    ad_match = any(
        re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        for word in ad_words
    )

    if not ad_match:
        return

    # ✅ Mark SAFE + get x_username
    user_row = await fetchrow(
        """
        UPDATE users
        SET ad_count = ad_count + 1,
            status = 'safe'
        WHERE chat_id=$1 AND tg_user_id=$2
        RETURNING id, x_username
        """,
        chat_id,
        user_id
    )

    if not user_row:
        return

    user_db_id = user_row["id"]
    x_username = user_row["x_username"]

    # 🔗 Get FIRST stored link (fixed for life)
    link_row = await fetchrow(
        """
        SELECT url
        FROM links
        WHERE user_id=$1
        ORDER BY id ASC
        LIMIT 1
        """,
        user_db_id
    )

    first_link = link_row["url"] if link_row else None

    # 🐦 Build display + click logic
    if x_username:
        # real username → clickable profile
        x_display = f'<a href="https://x.com/{x_username}">@{x_username}</a>'

    elif first_link:
        # no username → dummy @i → click opens first link
        x_display = f'<a href="{first_link}">@i</a>'

    else:
        x_display = "Unknown"

    await update.message.reply_text(
        f"𝕏 ID: {x_display}",
        parse_mode="HTML",
        disable_web_page_preview=True
    )

async def sr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # 🔐 Admin check
    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized")
        return

    # 🧾 Must reply to user's message
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user's AD message with /sr")
        return

    chat_id = update.effective_chat.id
    replied_user = update.message.reply_to_message.from_user
    user_id = replied_user.id
    username = replied_user.username or replied_user.full_name

    # 🔎 Check user exists + is SAFE
    user_row = await fetchrow(
        """
        SELECT status
        FROM users
        WHERE chat_id=$1 AND tg_user_id=$2
        """,
        chat_id,
        user_id
    )

    if not user_row:
        await update.message.reply_text("ℹ️ User data not found.")
        return

    if user_row["status"] != "safe":
        await update.message.reply_text("ℹ️ User is already unsafe.")
        return

    # 🔁 Reset to UNSAFE
    await execute(
        """
        UPDATE users
        SET status='unsafe',
            ad_count=0
        WHERE chat_id=$1 AND tg_user_id=$2
        """,
        chat_id,
        user_id
    )

    # ⚠️ Warning message
    await update.message.reply_text(
        f"⚠️ @{username} has been marked *UNSAFE* again.\n\n"
        "Your likes aren’t visible yet.\n"
        "Kindly complete them or share a screen recording with your profile visible.",
        parse_mode="Markdown"
    )


async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to mark a user as SAFE
    Usage: Reply to user's message with /ad
    """

    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "❌ Reply to a user's message with /ad"
        )
        return

    replied_user = update.message.reply_to_message.from_user
    user_id = replied_user.id
    chat_id = update.effective_chat.id

    # 🔍 Fetch user from DB
    user = await fetchrow(
        """
        SELECT username, status
        FROM users
        WHERE chat_id=$1 AND tg_user_id=$2
        """,
        chat_id,
        user_id
    )

    if not user:
        await update.message.reply_text("ℹ️ User data not found.")
        return

    if user["status"] == "safe":
        await update.message.reply_text("ℹ️ User is already SAFE.")
        return

    # ✅ Update user → SAFE
    await execute(
        """
        UPDATE users
        SET status='safe', ad_count=0
        WHERE chat_id=$1 AND tg_user_id=$2
        """,
        chat_id,
        user_id
    )

    await update.message.reply_text(
        f"✅ @{user['username']} has been marked SAFE!"
    )

async def show_ad_completed(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global link_counts

    # Calculate the total number of users who completed the ad task
    total_completed_users = sum(1 for data in link_counts.values() if data.get("ad_count", 0) > 0)

    # Send a message to the user with the total count
    if total_completed_users > 0:
        await update.message.reply_text(f"✅ {total_completed_users} users done task so far.")
    else:
        await update.message.reply_text("❌ No users have completed task yet.")

async def show_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await context.bot.send_sticker(update.effective_chat.id, STICKER_ID)
        return

    chat_id = update.effective_chat.id

    # 📥 Fetch unsafe users + LAST link they sent
    rows = await fetch(
        """
        SELECT
            u.username,
            l.url
        FROM users u
        LEFT JOIN LATERAL (
            SELECT url
            FROM links
            WHERE user_id = u.id
            ORDER BY id DESC
            LIMIT 1
        ) l ON TRUE
        WHERE u.chat_id = $1
          AND u.status != 'safe'
        ORDER BY u.id ASC
        """,
        chat_id
    )

    if not rows:
        await context.bot.send_message(chat_id, "All users are safe.")
        return

    TELEGRAM_ICON = "💬"
    X_ICON = "𝕏"

    lines = ["<b>Unsafe Users:</b>"]
    count = 0
    srno = 1

    for row in rows:
        tg_username = row["username"] or "Unknown"
        last_link = row["url"]

        # 👉 ALWAYS show @i
        # 👉 clickable ONLY if link exists
        if last_link:
            x_display = f'<a href="{last_link}">@i</a>'
        else:
            x_display = "@i"

        lines.append(
            f"{srno}. {TELEGRAM_ICON} @{tg_username} | {X_ICON}: {x_display}"
        )

        srno += 1
        count += 1

        # 📤 Send in batches of 80
        if count % 80 == 0:
            await context.bot.send_message(
                chat_id=chat_id,
                text="\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            lines = ["<b>Unsafe Users:</b>"]

    # 📤 Send remaining users
    if lines:
        await context.bot.send_message(
            chat_id=chat_id,
            text="\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True
        )

async def show_link_counts(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    chat_id = update.effective_chat.id

    # 📊 Fetch users who shared links
    rows = await fetch(
        """
        SELECT username, link_count
        FROM users
        WHERE chat_id=$1 AND link_count > 0
        ORDER BY link_count DESC
        """,
        chat_id
    )

    if not rows:
        await update.message.reply_text("No links counted yet!")
        return

    # 👥 Total users
    total_users = len(rows)

    # 🔗 Users with more than 1 link
    users_with_more_than_1 = [
        f"🔗 @{escape_markdown_v2(row['username'] or 'NoUsername')} → *{escape_markdown_v2(str(row['link_count']))}* links"
        for row in rows
        if row["link_count"] > 1
    ]

    # 🧾 Message
    counts_text = (
        "📊 *Link Tracking Report*\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Users with Links:* `{escape_markdown_v2(str(total_users))}`\n"
        "━━━━━━━━━━━━━━━━━━\n"
    )

    if users_with_more_than_1:
        counts_text += "\n".join(users_with_more_than_1)
    else:
        counts_text += "✅ No users with more than 1 link"

    await update.message.reply_text(
        counts_text,
        parse_mode=telegram.constants.ParseMode.MARKDOWN_V2
    )


async def multiple_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    chat_id = update.effective_chat.id

    # 📥 Fetch users with more than 2 links (3 or more)
    rows = await fetch(
        """
        SELECT u.id, u.tg_user_id, u.username, u.full_name, COUNT(l.id) AS link_count,
               ARRAY_AGG(l.url) AS links
        FROM users u
        JOIN links l ON l.user_id = u.id
        WHERE u.chat_id = $1
        GROUP BY u.id
        HAVING COUNT(l.id) > 1
        ORDER BY u.id ASC
        """,
        chat_id
    )

    if not rows:
        await update.message.reply_text("No users with more than 2 links found.")
        return

    TELEGRAM_ICON = "💬"
    lines = ["🚨 Users with more than 2 links 🚨\n"]
    srno = 1

    for row in rows:
        # Telegram display
        display_name = f"@{row['username']}" if row['username'] else row['full_name'] or "Unknown"

        lines.append(f"{srno}. {TELEGRAM_ICON} {display_name}")

        # Links list as clickable "link1", "link2", ...
        links = row.get("links") or []
        for idx, link in enumerate(links, start=1):
            if not link.startswith(("http://", "https://")):
                link = f"https://{link}"  # ensure clickable
            lines.append(f"<a href='{link}'>@link{idx}</a>")

        lines.append("")  # empty line after each user
        srno += 1

        # 📤 Send in batches of 50 users
        if srno % 50 == 0:
            await update.message.reply_text(
                "\n".join(lines),
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            lines = ["🚨 Users with more than 2 links 🚨\n"]

    # Send remaining users
    if lines:
        await update.message.reply_text(
            "\n".join(lines),
            parse_mode="HTML",
            disable_web_page_preview=True
        )


async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 🔐 Admin check
    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized access attempt!")
        return

    chat_id = update.effective_chat.id

    # 📥 Fetch users who shared at least 1 link + last link
    rows = await fetch(
        """
        SELECT u.id, u.username, u.x_username, ARRAY_AGG(l.url ORDER BY l.id ASC) AS links
        FROM users u
        LEFT JOIN links l ON l.user_id = u.id
        WHERE u.chat_id = $1 AND u.link_count > 0
        GROUP BY u.id
        ORDER BY u.id ASC
        """,
        chat_id
    )

    if not rows:
        await update.message.reply_text("🔴 No users found!")
        return

    TELEGRAM_ICON = "💬"
    X_ICON = "𝕏"
    user_list_text = "<b>Users List:</b>\n"
    count = 0
    srno = 1

    for row in rows:
        tg_username = row["username"] or "Unknown"
        x_value = row["x_username"]
        links = row.get("links") or []

        # 🐦 Last link for clickable X
        last_link = links[-1] if links else "https://x.com/i"

        # X username display
        if x_value:
            display_name = f"@{x_value}"
        else:
            display_name = "@i"  # dummy

        # clickable link
        x_display = f'<a href="{last_link}">{display_name}</a>'

        user_list_text += (
            f"{srno}. {TELEGRAM_ICON} @{tg_username} | {X_ICON}: {x_display}\n"
        )

        srno += 1
        count += 1

        # 📤 Send in batches of 80
        if count % 80 == 0:
            await update.message.reply_text(
                user_list_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            user_list_text = "<b>Users List:</b>\n"

    # 📤 Send remaining users
    if user_list_text.strip():
        await update.message.reply_text(
            user_list_text,
            parse_mode="HTML",
            disable_web_page_preview=True
        )



async def show_checklist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global link_counts

    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"

        await update.message.reply_sticker(STICKER_ID)  # Send sticker
        return  # Stop execution if user is not an admin
    # Create a list to store the checklist entries
    checklist = []

    # Loop through all users and their data in link_counts
    for user_data in link_counts.values():
        srno = user_data["srno"]
        name = user_data["name"]
        ad_completed = "✅" if user_data.get("ad_count", 0) > 0 else "❌"

        checklist.append(f"{srno}. {name} - {ad_completed}")

    # Join all the entries into a single string
    checklist_text = "\n".join(checklist)

    # Send the checklist as a message
    if checklist_text:
        await update.message.reply_text(f"📋 Checklist:\n{checklist_text}")
    else:
        await update.message.reply_text("❌ No users found in the list.")

async def mute_all_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    if not unsafe_users:
        await update.message.reply_text("No unsafe users to mute.")
        return

    chat = update.effective_chat
    bot_member = await chat.get_member(context.bot.id)

    if not bot_member.can_restrict_members:
        await update.message.reply_text("Bot needs Manage Members permission.")
        return

    # 🔒 DEFAULT MUTE DURATION → 5 DAYS
    mute_duration = timedelta(days=5)
    until_date = update.message.date + mute_duration

    muted = 0
    failed = 0

    for user_id in list(unsafe_users.keys()):
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat.id,
                user_id=user_id,
                permissions=ChatPermissions(can_send_messages=False),
                until_date=until_date
            )
            muted += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"Muted {muted} unsafe users"
        + (f"\nFailed: {failed}" if failed else "")
    )

    await lock_chat(update, context)



async def mute_user(update, context):
    if not await is_admin(update):
        await update.message.reply_text("🚫 Admin only")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user to mute them")
        return

    user_id = update.message.reply_to_message.from_user.id

    # Mute for 5 days
    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=user_id,
        permissions=ChatPermissions(can_send_messages=False),
        until_date=update.message.date + timedelta(days=5)
    )

    await update.message.reply_text("✅ User muted for 5 days")



async def unmute_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("🚫 Admin only")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user to unmute")
        return

    user_id = update.message.reply_to_message.from_user.id

    await context.bot.restrict_chat_member(
        chat_id=update.effective_chat.id,
        user_id=user_id,
        permissions=ChatPermissions(
            can_send_messages=True
        )
    )

    await update.message.reply_text("✅ User unmuted")

async def start_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    chat_id = update.effective_chat.id

    # 🕒 Time (IST)
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    end_time = now + timedelta(hours=1)
    end_time_str = end_time.strftime("%I:%M %p")

    # 🧠 ENABLE TRACKING (DB)
    await execute(
        """
        UPDATE sessionsdata
        SET tracking_enabled = true,
            end_time = $2
        WHERE chat_id = $1
        """,
        chat_id,
        end_time
    )

    # 🔁 Update Group Name → CLOSED
    try:
        await context.bot.set_chat_title(
            chat_id=chat_id,
            title="VERIFIED LIKE GC [CLOSED]"
        )
    except Exception as e:
        logger.warning(f"Group title update failed: {e}")

    # 🔒 Change permissions
    try:
        await context.bot.set_chat_permissions(
            chat_id=chat_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False
            )
        )
    except Exception as e:
        logger.warning(f"Permission update failed: {e}")

    # 📢 Announcement
    msg = await update.message.reply_text(
        "📢 Timeline Updated 👇\n\n"
        "🔗 https://x.com/glamm__girl\n\n"
        "❤️ Like all posts of the TL account\n"
        "📝 Drop All done in the group after completion\n\n"
        f"⏰ Last time for activity: {end_time_str}\n\n"
        "✅ Tracking words: done, ad, all done",
        disable_web_page_preview=True
    )

    # 📌 Pin message
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True
        )
    except Exception as e:
        logger.warning(f"Pin message failed: {e}")


# Command to stop ad tracking (optional)
async def stop_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tracking_enabled

    # Check if the user is an admin
    if not await is_admin(update):
        await update.message.reply_text("You are not authorized to use this command.")
        return

    tracking_enabled = False
    await update.message.reply_text("Ad trackinghas been deactivated!")


async def get_user_id(context: ContextTypes.DEFAULT_TYPE, username: str):
    """Convert username (@username) to user ID even if they haven't sent a message."""
    try:
        user = await context.bot.get_chat(username)  # ✅ Resolves username to user ID
        return user.id
    except Exception:
        return None


async def kick_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Kick a user from the group (Admins only)."""

    chat = update.effective_chat

    # # ✅ Ensure the bot has permission to kick
    # if not await bot_has_permissions(update, context):
    #     await update.message.reply_text("I need 'Ban Members' permission to kick users.")
    #     return

    if not await is_admin(update):
            STICKER_ID = "7688271168:AAFpBE6eZc8-vI1qRSmdK7ayOMVXEoVoLcI"

            await update.message.reply_sticker(STICKER_ID)  # Send sticker
            return  # Stop execution if user is not an admin

    target_user_id = None
    target_username = None

    try:
        # ✅ Kick by replying to a user
        if update.message.reply_to_message:
            target_user_id = update.message.reply_to_message.from_user.id
            target_username = f"@{update.message.reply_to_message.from_user.username}" if update.message.reply_to_message.from_user.username else "Unknown User"
        else:
            # ✅ Kick by @username
            if not context.args:
                await update.message.reply_text("Usage: /kick @username or reply to a user.")
                return

            target_username = context.args[0].replace("@", "")

            # ✅ Convert username to user ID
            target_user_id = await get_user_id(context, f"@{target_username}")

            if not target_user_id:
                await update.message.reply_text(f"User @{target_username} not found in Telegram.")
                return

        # ✅ Check if user is in the group
        try:
            user_status = await context.bot.get_chat_member(chat.id, target_user_id)
        except Exception:
            await update.message.reply_text(f"User @{target_username} is not in this group.")
            return

        # ✅ Prevent kicking admins
        if user_status.status in ["administrator", "creator"]:
            await update.message.reply_text(f"Cannot kick an admin: @{target_username}")
            return



        # ✅ Kick the user
        await context.bot.ban_chat_member(chat.id, target_user_id)

        # ✅ Notify the chat
        await update.message.reply_text(
            f"User Kicked: @{target_username}\n"
            f"Action: Removed from group"
        )

    except Exception as e:
        await update.message.reply_text(f"Failed to kick user: {e}")


async def lock_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("🚫 Admin only command")
        return

    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
            permissions=ChatPermissions(
                can_send_messages=False
            )
        )

        await update.message.reply_text("🔒 Chat locked successfully")

    except Exception as e:
        print("Failed to lock chat:", e)
        await update.message.reply_text("❌ Failed to lock chat")


def build_bot():
    BOT_TOKEN = os.getenv("BOT_TOKEN")

    if not BOT_TOKEN:
        raise RuntimeError("❌ BOT_TOKEN environment variable not set")

    application = Application.builder().token(BOT_TOKEN).build()

    # =========================
    # Command handlers
    # =========================
    application.add_handler(CommandHandler("open", start))
    application.add_handler(CommandHandler("count", show_link_counts))
    application.add_handler(CommandHandler("unsafe", show_unsafe_users))
    application.add_handler(CommandHandler("mute", mute_user))
    application.add_handler(CommandHandler("unmute", unmute_user))
    application.add_handler(CommandHandler("tracking", start_ad))
    application.add_handler(CommandHandler("stop_ad", stop_ad))
    application.add_handler(CommandHandler("mult", multiple_links))
    application.add_handler(CommandHandler("list", user_list))
    application.add_handler(CommandHandler("count_ad", show_ad_completed))
    application.add_handler(CommandHandler("testlist", show_checklist))
    application.add_handler(CommandHandler("muteall", mute_all_unsafe_users))
    application.add_handler(CommandHandler("kick", kick_user))
    application.add_handler(CommandHandler("l", lock_chat))
    application.add_handler(CommandHandler("sr", sr_command))
    application.add_handler(CommandHandler("ad", ad_command))

    # =========================
    # Message handlers
    # =========================
    application.add_handler(
        MessageHandler(
            filters.Entity("url") | filters.Entity("text_link"),
            count_links
        )
    )

    application.add_handler(
        MessageHandler(
            filters.TEXT | filters.PHOTO | filters.VIDEO | filters.Document.ALL,
            count_ad_messages
        )
    )

    return application