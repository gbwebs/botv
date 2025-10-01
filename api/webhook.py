# api/webhook.py
from fastapi import FastAPI, Request
from mangum import Mangum
from telegram import Update
from bot.telegram_bot import build_bot

app = FastAPI()
bot_app = build_bot()

@app.on_event("startup")
async def startup_event():
    # Initialize bot once FastAPI is ready
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
    data = await request.json()
    print("📩 Raw update:", data)

    try:
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        print("✅ Update processed")
    except Exception as e:
        print("❌ Error processing update:", e)

    return {"status": "received"}

handler = Mangum(app)
