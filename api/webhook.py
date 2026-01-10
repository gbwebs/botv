from fastapi import FastAPI, Request
from telegram import Update
from bot.telegram_bot import build_bot
import asyncio

app = FastAPI()
bot_app = build_bot()

bot_lock = asyncio.Lock()

async def init_bot_once():
    if not getattr(bot_app, "_initialized", False):
        async with bot_lock:
            if not getattr(bot_app, "_initialized", False):
                await bot_app.initialize()
                bot_app._initialized = True
                print("✅ Bot initialized safely")

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)

        # Safe init
        await init_bot_once()

        await bot_app.process_update(update)
        return {"status": "ok"}

    except Exception as e:
        print("❌ Webhook processing failed:", e)
        return {"status": "error", "detail": str(e)}, 500
