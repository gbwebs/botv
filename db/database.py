# db/database.py
import asyncpg
import os

pool = None

DATABASE_URL = os.getenv("DATABASE_URL")

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            ssl="require",
            min_size=1,
            max_size=1,
            timeout=10,
        )

async def ensure_db():
    if pool is None:
        await init_db()

async def fetchrow(query: str, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def execute(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.execute(query, *args)

async def fetch(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetch(query, *args)
    

