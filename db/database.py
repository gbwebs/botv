import asyncpg
import os

pool: asyncpg.Pool | None = None

async def init_db():
    global pool
    if pool:
        return

    pool = await asyncpg.create_pool(
        dsn=os.environ["DATABASE_URL"],
        min_size=1,
        max_size=1,
        ssl="require",
        timeout=30,
    )

async def execute(query, *args):
    async with pool.acquire() as con:
        return await con.execute(query, *args)

async def fetch(query, *args):
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def fetchrow(query, *args):
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)
