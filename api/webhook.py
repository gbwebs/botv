from fastapi import FastAPI, Request
from telegram import Update
from bot.telegram_bot import build_bot

app = FastAPI()
bot_app = None  # global

@app.on_event("startup")
async def startup_event():
    global bot_app
    bot_app = await build_bot()   # ✅ AWAIT HERE
    await bot_app.initialize()
    print("✅ Bot initialized")

@app.on_event("shutdown")
async def shutdown_event():
    await bot_app.shutdown()
    print("🛑 Bot shutdown cleanly")

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)

        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        print("❌ Webhook processing failed:", e)
        return {"status": "error", "detail": str(e)}
