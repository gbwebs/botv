# api/webhook.py
from fastapi import FastAPI, Request
from mangum import Mangum

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Hello, Vercel!"}

@app.post("/")
async def telegram_webhook(req: Request):
    data = await req.json()
    # handle Telegram webhook payload here
    return {"status": "ok"}

# export the serverless handler
handler = Mangum(app)
