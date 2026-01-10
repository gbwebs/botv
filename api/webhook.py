from fastapi import FastAPI
from bot.telegram_bot import build_bot
from db.database import init_db

app = FastAPI()

bot_app = build_bot()

# Flags to prevent double initialization
_initialized = False
_db_initialized = False

@app.on_event("startup")
async def startup_event():
    global _initialized, _db_initialized
    try:
        # DB init only once
        if not _db_initialized:
            await init_db()
            _db_initialized = True
            print("✅ Database initialized")

        # Bot init only once
        if not _initialized:
            await bot_app.initialize()
            _initialized = True
            print("✅ Bot initialized")

    except Exception as e:
        print("❌ Startup failed:", e)
