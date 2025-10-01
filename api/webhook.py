from fastapi import FastAPI, Request
from mangum import Mangum
import os
from bot.telegram_bot import build_bot

app = FastAPI()
bot_app = build_bot()

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = bot_app.update_queue.put_nowait(data)  # Feed Telegram update
    await bot_app.update_queue.put(data)
    await bot_app.process_update(data)  # Process immediately
    return {"status": "received"}

handler = Mangum(app)
