import asyncpg
import os

pool = None

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],
            min_size=1,
            max_size=5,
            command_timeout=60
        )

async def fetchrow(query, *args):
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def fetch(query, *args):
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def execute(query, *args):
    async with pool.acquire() as con:
        return await con.execute(query, *args)
