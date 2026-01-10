from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from telegram import Update
from bot.telegram_bot import build_bot
from db.database import init_db

app = FastAPI()
bot_app = build_bot()

_initialized = False
_db_initialized = False

async def ensure_startup():
    global _initialized, _db_initialized
    if not _db_initialized:
        await init_db()
        _db_initialized = True
        print("✅ DB initialized")
    if not _initialized:
        await bot_app.initialize()
        _initialized = True
        print("✅ Bot initialized")

@app.get("/")
async def root():
    return {"status": "ok", "service": "telegram-bot"}

@app.post("/api/webhook")
async def telegram_webhook(request: Request):
    try:
        await ensure_startup()
        data = await request.json()
        update = Update.de_json(data, bot_app.bot)
        await bot_app.process_update(update)
        return {"status": "ok"}
    except Exception as e:
        print("❌ Webhook failed:", e)
        return JSONResponse(content={"status": "error", "detail": str(e)}, status_code=500)
