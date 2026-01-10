# api/webhook.py
from fastapi import FastAPI, Request
from telegram import Update
from bot.telegram_bot import build_bot
from db.database import init_db  # 👈 your DB init

app = FastAPI()

# Initialize bot and DB references
bot_app = build_bot()
db_initialized = False

@app.on_event("startup")
async def startup_event():
    """
    Initialize both the database and the bot once on cold start.
    """
    global db_initialized

    try:
        # Initialize database pool
        if not db_initialized:
            await init_db()
            db_initialized = True
            print("✅ Database initialized")

        # Initialize Telegram bot
        if not getattr(bot_app, "_initialized", False):
            await bot_app.initialize()
            bot_app._initialized = True
            print("✅ Bot initialized")

    except Exception as e:
        print("❌ Startup failed:", e)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Graceful shutdown
    """
    try:
        await bot_app.shutdown()
        print("🛑 Bot shutdown cleanly")
    except Exception as e:
        print("⚠️ Shutdown error:", e)


@app.get("/")
async def root():
    return {"status": "ok", "service": "telegram-bot"}


@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    """
    Telegram webhook handler
    """
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)

        # Lazy check: ensure bot is initialized (serverless safe)
        if not getattr(bot_app, "_initialized", False):
            await bot_app.initialize()
            bot_app._initialized = True

        await bot_app.process_update(update)
        return {"status": "ok"}

    except Exception as e:
        print("❌ Webhook processing failed:", e)
        return {"status": "error", "detail": str(e)}, 500
