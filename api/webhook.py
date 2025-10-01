from fastapi import FastAPI, Request
from mangum import Mangum

app = FastAPI()

@app.get("/")
def hello():
    return {"message": "Hello, Vercel!"}

handler = Mangum(app)  # <-- export this for Vercel
