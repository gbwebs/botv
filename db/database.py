# db/database.py
import asyncpg
import os
import asyncio

pool = None
db_lock = asyncio.Lock()

async def init_db():
    global pool
    if pool is None:
        if "DATABASE_URL" not in os.environ:
            raise RuntimeError("❌ DATABASE_URL not set")

        pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=1,
            max_size=5,
            command_timeout=60
        )
        print("✅ Database pool initialized")

async def ensure_db():
    global pool
    if pool is None:
        async with db_lock:
            if pool is None:
                await init_db()

async def fetchrow(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def fetch(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def execute(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.execute(query, *args)
