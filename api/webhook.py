# api/webhook.py
from fastapi import FastAPI, Request
from mangum import Mangum
from bot.telegram_bot import build_bot
from telegram import Update

app = FastAPI()
bot_app = build_bot()  # single instance

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/")
async def telegram_webhook(request: Request):
    data = await request.json()

    # Convert dict to Update object
    update = Update.de_json(data, bot_app.bot)

    # Process the update
    await bot_app.process_update(update)

    return {"status": "received"}

handler = Mangum(app)
