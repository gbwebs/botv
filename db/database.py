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
            max_size=5,          # allow small pool
            timeout=10,
            statement_cache_size=0  # 🔥 disable prepared statements
        )

async def ensure_db():
    if pool is None:
        await init_db()

async def fetchrow(query: str, *args):
    await ensure_db()
    async with pool.acquire() as con:
        # 🔹 Explicitly disable prepared statements for this connection
        async with con.transaction():
            return await con.fetchrow(query, *args)

async def execute(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        async with con.transaction():
            return await con.execute(query, *args)

async def fetch(query: str, *args):
    await ensure_db()
    async with pool.acquire() as con:
        async with con.transaction():
            return await con.fetch(query, *args)
