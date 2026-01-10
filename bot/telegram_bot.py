from telegram import Update, Chat, ChatPermissions
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from datetime import datetime, timedelta
import telegram
import logging
import re
import os
from db.database import fetchrow, fetch, execute


def escape_markdown_v2(text):
    escape_chars = r"_*[]()~`>#+-=|{}.!"
    return "".join(f"\\{char}" if char in escape_chars else char for char in text)
# Enable logging
logging.basicConfig(format='%(asctime)s - %(message)s', level=logging.WARNING)
logger = logging.getLogger(__name__)

# Dictionary to store user link counts and unsafe users
link_counts = {}
unsafe_users = {}
safe_users = {}
# Add a global flag for tracking system
tracking_enabled = False
# Words to check for exact matches
ad_words = {"ad", "all done", "AD", "all dn", "alldone","done"}


excluded_users = {
    "OMEGA_908",
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
    # Fetch chat administrators and check if the user is one of them
    admins = await chat.get_administrators()
    for admin in admins:
        if admin.user.id == user_id:
            return True
    return False

# Start command to reset all counts
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    # Check admin
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    global link_counts, unsafe_users, safe_users
    link_counts = {}
    unsafe_users = {}
    safe_users = {}

    chat_id = update.effective_chat.id

    # 🔁 Update Group Name
    try:
        await context.bot.set_chat_title(
            chat_id=chat_id,
            title="VERIFIED LIKE GC [OPEN]"
        )
    except Exception as e:
        print("Failed to update group title:", e)

    # 🔒 Change permissions → TEXT ONLY
    try:
        await context.bot.set_chat_permissions(
            chat_id=update.effective_chat.id,
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
        print("Failed to update permissions:", e)

    await execute(
        """
        INSERT INTO public.sessions (chat_id, tracking_enabled)
        VALUES ($1, false)
        ON CONFLICT (chat_id)
        DO UPDATE SET
            tracking_enabled=false,
            start_time=NOW(),
            end_time=NULL
        """,
        chat_id
    )

    # 📌 Stylish message
    msg = await update.message.reply_text(
        "🚀 Session Started Successfully!\n\n"
        "🔗 Send your links below\n"
    )

    # 📌 Pin the message
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True
        )
    except Exception as e:
        print("Failed to pin message:", e)


# Message handler to count messages with links
async def count_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global link_counts, unsafe_users, safe_users, excluded_users

    if not update.message:
        return

    user = update.message.from_user
    user_id = user.id
    user_full_name = user.full_name
    user_username = user.username or "NoUsername"

    # Skip excluded users
    if user_username in excluded_users:
        return

    # Init user
    if user_id not in link_counts:
        link_counts[user_id] = {
            "srno": len(link_counts) + 1,
            "name": user_full_name,
            "username": user_username,
            "x_username": None,
            "link_count": 0,
            "ad_count": 0,
            "links": []  # NEW: store all links
        }

    if not update.message.entities:
        return

    for entity in update.message.entities:
        if entity.type not in ["url", "text_link"]:
            continue

        # Extract URL
        url = update.message.text[entity.offset:entity.offset + entity.length]

        # Extract X username
        x_username = None
        try:
            if "twitter.com/" in url:
                x_username = url.split("twitter.com/")[-1].split("/")[0].split("?")[0]
            elif "x.com/" in url:
                x_username = url.split("x.com/")[-1].split("/")[0].split("?")[0]
        except:
            x_username = None

        # ❗ INVALID usernames (like i, status, etc.)
        INVALID_X = {"i", "status", ""}

        # SAVE ONLY ONCE
        if not link_counts[user_id].get("x_username"):
            if x_username and x_username not in INVALID_X:
                # ✅ store username
                link_counts[user_id]["x_username"] = f"{x_username}"
            else:
                # ✅ store clickable link
                link_counts[user_id]["x_username"] = url

        # Increment link count ALWAYS
        link_counts[user_id]["link_count"] += 1

        # Add the link to the list
        if url not in link_counts[user_id]["links"]:
            link_counts[user_id]["links"].append(url)

        # Mark unsafe initially
        if user_id not in unsafe_users and user_id not in safe_users:
            unsafe_users[user_id] = {
                "srno": link_counts[user_id]["srno"],
                "name": user_full_name,
                "username": user_username,
                "x_username": link_counts[user_id]["x_username"],
                "links": link_counts[user_id]["links"],
            }
        # DB: upsert user
        user_row = await fetchrow(
            """
            INSERT INTO users (chat_id, tg_user_id, username, full_name, x_username, link_count)
            VALUES ($1,$2,$3,$4,$5,1)
            ON CONFLICT (chat_id, tg_user_id)
            DO UPDATE SET
                link_count = users.link_count + 1,
                x_username = COALESCE(users.x_username, EXCLUDED.x_username)
            RETURNING id
            """,
            update.effective_chat.id,
            user_id,
            user_username,
            user_full_name,
            link_counts[user_id]["x_username"]
        )

        # DB: store link
        await execute(
            "INSERT INTO links (user_id, url) VALUES ($1,$2)",
            user_row["id"],
            url
        )


        # ⚠️ Alert ONLY if more than 1 link
        if link_counts[user_id]["link_count"] > 1:
            mention = f"@{user_username}" if user.username else user_full_name
            await update.message.reply_text(
                f"⚠️ Alert: {mention} shared more than one link."
            )

        break  # one link per message

async def count_ad_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global link_counts, unsafe_users, safe_users

    if not update.message or not tracking_enabled:
        return

    user = update.message.from_user
    user_id = user.id

    # user must already exist
    if user_id not in link_counts:
        return

    # combine text
    text = (update.message.text or "") + " " + (update.message.caption or "")

    ad_match = any(
        re.search(rf"\b{re.escape(word)}\b", text, re.IGNORECASE)
        for word in ad_words
    )

    user_data = link_counts[user_id]

    if ad_match:
        # increment ad count
        user_data["ad_count"] += 1

        # remove from unsafe
        unsafe_users.pop(user_id, None)

        # ✅ SAFE USER (FULL STRUCTURE)
        safe_users[user_id] = {
            "srno": user_data["srno"],
            "name": user_data["name"],
            "username": user_data["username"],
            "x_username": user_data["x_username"],
            "links": user_data["links"],
        }

        x_username = user_data.get("x_username")

        x_display = "Unknown"

        # Case 1: x_username exists
        if x_username:
            # if username itself is a link
            if x_username.startswith(("http://", "https://")):
                x_display = x_username
            else:
                # normal username → show username + link
                x_display = f"@{x_username}"

        await update.message.reply_text(
            f"𝕏 ID: {x_display}",
            disable_web_page_preview=True
        )

        # DB: mark safe + increment ad count
        await execute(
            """
            UPDATE users
            SET ad_count = ad_count + 1,
                status = 'safe'
            WHERE chat_id=$1 AND tg_user_id=$2
            """,
            update.effective_chat.id,
            user_id
        )


    else:
        # ✅ UNSAFE USER (FULL STRUCTURE)
        if user_id not in safe_users and user_id not in unsafe_users:
            unsafe_users[user_id] = {
                "srno": user_data["srno"],
                "name": user_data["name"],
                "username": user_data["username"],
                "x_username": user_data["x_username"],
                "links": user_data["links"],
            }



# Admin /sr command when replying to an AD message
async def sr_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global safe_users, unsafe_users, link_counts

    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user's AD message with /sr")
        return

    replied_user = update.message.reply_to_message.from_user
    user_id = replied_user.id

    if user_id not in link_counts:
        await update.message.reply_text("ℹ️ User data not found.")
        return

    if user_id not in safe_users:
        await update.message.reply_text("ℹ️ User is already unsafe.")
        return

    user_data = link_counts[user_id]

    # Reset ad count
    user_data["ad_count"] = 0

    # Move SAFE → UNSAFE
    unsafe_users[user_id] = {
        "srno": user_data["srno"],
        "name": user_data["name"],
        "username": user_data["username"],
        "x_username": user_data["x_username"],
        "links": user_data["links"],
    }

    safe_users.pop(user_id, None)

    await execute(
        "UPDATE users SET status='unsafe', ad_count=0 WHERE chat_id=$1 AND tg_user_id=$2",
        update.effective_chat.id,
        user_id
    )


    await update.message.reply_text(
        f"⚠️ @{user_data['username']} has been marked **UNSAFE** again.\n\n"
        "Your likes aren’t visible yet.\n"
        "Kindly complete them or share a screen recording with your profile visible."
    )

async def ad_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Admin command to mark a user as SAFE if they are currently in the UNSAFE list.
    Usage: Reply to the user's message with /ad
    """
    global safe_users, unsafe_users, link_counts

    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Reply to a user's message with /ad to mark them safe")
        return

    replied_user = update.message.reply_to_message.from_user
    user_id = replied_user.id

    if user_id not in link_counts:
        await update.message.reply_text("ℹ️ User data not found.")
        return

    if user_id not in unsafe_users:
        await update.message.reply_text("ℹ️ User is already safe.")
        return

    user_data = link_counts[user_id]

    # Reset ad count
    user_data["ad_count"] = 0

    # Move UNSAFE → SAFE
    safe_users[user_id] = {
        "srno": user_data["srno"],
        "name": user_data["name"],
        "username": user_data["username"],
        "x_username": user_data["x_username"],
        "links": user_data["x_username"]
    }

    unsafe_users.pop(user_id, None)

    await execute(
        "UPDATE users SET status='safe', ad_count=0 WHERE chat_id=$1 AND tg_user_id=$2",
        update.effective_chat.id,
        user_id
    )


    await update.message.reply_text(
        f"✅ @{user_data['username']} has been marked SAFE!\n\n"
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

# Command to show unsafe users

def format_x_value(x_value):
    if not x_value:
        return "NA"

    if x_value.startswith("http"):
        return f'<a href="{x_value}">Link</a>'

    return f"@{x_value}"


async def show_unsafe_users(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await context.bot.send_sticker(update.effective_chat.id, STICKER_ID)
        return

    if not unsafe_users:
        await context.bot.send_message(
            update.effective_chat.id,
            "All users are safe."
        )
        return

    lines = ["Unsafe Users:"]

    for idx, data in enumerate(unsafe_users.values(), start=1):
        tg_username = data.get("username", "Unknown")
        x_display = format_x_value(data.get("x_username"))

        lines.append(
            f"{idx}. @{tg_username} | X:{x_display}"
        )

    await context.bot.send_message(
        chat_id=update.effective_chat.id,
        text="\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True
    )



# Command to show link counts
async def show_link_counts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Check if the user is an admin
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"

        await update.message.reply_sticker(STICKER_ID)  # Send sticker
        return  # Stop execution if user is not an admin

    if not link_counts:
        await update.message.reply_text("No links counted yet!")
        return

    # Count total users who shared links
    total_users = sum(1 for data in link_counts.values() if data['link_count'] > 0)

    # Find users who shared more than 2 links
    users_with_more_than_2_links = [
        f"🔗 @{escape_markdown_v2(data['username'])} → *{escape_markdown_v2(str(data['link_count']))}* links"
        for data in link_counts.values()
        if data['link_count'] > 1
    ]

    # Construct the message with escaped characters
    counts_text = (
        f"📊 *Link Tracking Report*\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 *Total Users with Links:* `{escape_markdown_v2(str(total_users))}`\n"
        f"━━━━━━━━━━━━━━━━━━\n"
    )

    if users_with_more_than_2_links:
        counts_text += "\n".join(users_with_more_than_2_links)
    else:
        counts_text += "✅ No users with more than 1 links"

    await update.message.reply_text(counts_text, parse_mode=telegram.constants.ParseMode.MARKDOWN_V2)

async def multiple_links(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    if not link_counts:
        await update.message.reply_text("No one shared links yet!")
        return

    response_text = "🚨 Users with multiple links or duplicate X usernames 🚨\n\n"
    rows_added = False

    for data in link_counts.values():
        link_count = data.get("link_count", 0)
        x_username = data.get("x_username")
        links = data.get("links", [])

        include = False

        # multiple links
        if link_count > 1:
            include = True

        # duplicate X username
        if x_username:
            same_x_users = [
                u for u in link_counts.values()
                if u.get("x_username") == x_username
            ]
            if len(same_x_users) > 1:
                include = True

        if not include:
            continue

        rows_added = True

        # BEST display name: TG username else full name
        display_name = f"@{data['username']}" if data.get("username") else data.get("name", "Unknown")

        # Add user info and all their links
        response_text += f"{data['srno']}. {display_name} | X: @{x_username or 'NA'}\n"
        for idx, link in enumerate(links, start=1):
            response_text += f"   {idx}. {link}\n"
        response_text += "\n"  # empty line after each user

    if not rows_added:
        await update.message.reply_text("No multiple or duplicate X users found.")
        return

    # Send the final message
    await update.message.reply_text(response_text)


async def user_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update):
        await update.message.reply_text("🚫 Unauthorized access attempt!")
        return

    if not link_counts:
        await update.message.reply_text("🔴 No users found!")
        return

    TELEGRAM_ICON = "💬"
    X_ICON = "𝕏"

    user_list_text = "Users List:\n"
    user_count = 0

    for data in link_counts.values():
        srno = data.get("srno")
        tg_username = data.get("username", "Unknown")
        x_value = data.get("x_username")

        # Decide how to show X value
        if x_value and x_value.startswith("http"):
            x_display = f'<a href="{x_value}">Link</a>'
        elif x_value:
            x_display = f'@{x_value}'
        else:
            x_display = "NA"

        user_list_text += (
            f"{srno}. {TELEGRAM_ICON} @{tg_username} | "
            f"{X_ICON} {x_display}\n"
        )

        user_count += 1

        # Send in batches of 80
        if user_count % 80 == 0:
            await update.message.reply_text(
                user_list_text,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
            user_list_text = "Users List:\n"

    # Send remaining users
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

# Command to enable ad tracking
async def start_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global tracking_enabled

    # 🔐 Admin check
    if not await is_admin(update):
        STICKER_ID = "CAACAgUAAxkBAAICLWfAVQEf_k6dGDuoUbGDUrcng0BlAAJWBQACDLDZVke9Qr6WRu8KNgQ"
        await update.message.reply_sticker(STICKER_ID)
        return

    tracking_enabled = True
    chat_id = update.effective_chat.id

    # 🕒 Time calculation (now + 1 hour)
    # now = datetime.now(datetime.astimezone)
 
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)
    
    end_time = now + timedelta(hours=1)
    end_time_str = end_time.strftime("%I:%M %p")  # e.g. 05:30 PM

    # 🔁 Update Group Name → CLOSED
    try:
        await context.bot.set_chat_title(
            chat_id=chat_id,
            title="VERIFIED LIKE GC [CLOSED]"
        )
    except Exception as e:
        print("Failed to update group title:", e)

    # 🔒 Change permissions (TEXT ONLY)
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
        print("Failed to update permissions:", e)

    # 📢 Message
    msg = await update.message.reply_text(
        "📢 Timeline Updated 👇\n\n"
        "🔗 x.com/glamm__girl\n\n"
        "❤️ Like all posts of the TL account\n"
        "📝 Drop All done in the group after completion\n\n"
        f"⏰ Last time for activity: {end_time_str}\n\n"
        "✅ Tracking words: done, ad, all done"
    )

    # 📌 Pin the message
    try:
        await context.bot.pin_chat_message(
            chat_id=chat_id,
            message_id=msg.message_id,
            disable_notification=True
        )
    except Exception as e:
        print("Failed to pin message:", e)

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