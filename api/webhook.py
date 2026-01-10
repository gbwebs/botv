# api/webhook.py

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update

from bot.telegram_bot import build_bot
from db.database import init_db  # DB init

app = FastAPI()

# Build telegram application
bot_app = build_bot()


@app.on_event("startup")
async def startup_event():
    """
    Runs once per cold start.
    Initializes DB + Telegram bot safely.
    """
    try:
        # Initialize database connection pool
        await init_db()

        # Initialize telegram bot only once
        if not getattr(bot_app, "_initialized", False):
            await bot_app.initialize()  # Must initialize before processing updates
            bot_app._initialized = True

        print("✅ Bot + Database initialized")

    except Exception as e:
        print("❌ Startup failed:", e)


@app.on_event("shutdown")
async def shutdown_event():
    """
    Graceful shutdown (Vercel may or may not call this)
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

        # Process update safely
        await bot_app.process_update(update)

        return {"status": "ok"}

    except Exception as e:
        # Catch all errors to prevent webhook failure
        print("❌ Webhook processing failed:", e)
        return JSONResponse(
            content={"status": "error", "detail": str(e)},
            status_code=500
        )
