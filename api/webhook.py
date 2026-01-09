# api/webhook.py
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update
from bot.telegram_bot import build_bot

app = FastAPI()
bot_app = build_bot()

@app.on_event("startup")
async def startup_event():
    if not getattr(bot_app, "_initialized", False):
        await bot_app.initialize()
        bot_app._initialized = True
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
        return JSONResponse(content={"status": "error", "detail": str(e)}, status_code=500)
