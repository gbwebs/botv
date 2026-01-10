# db/database.py
import asyncpg
import os
import asyncio

pool = None
lock = asyncio.Lock()

async def init_db():
    global pool

    if pool is not None:
        return

    async with lock:
        if pool is not None:
            return

        pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=1,
            max_size=1,  # 🔴 MUST BE 1 on Vercel
            command_timeout=30,
            max_inactive_connection_lifetime=30,
        )

        print("✅ Supabase pool connected")

async def ensure_db():
    if pool is None:
        await init_db()

async def execute(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.execute(query, *args)

async def fetch(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def fetchrow(query, *args):
    await ensure_db()
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)
