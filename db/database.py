# db/database.py
import asyncpg
import os

pool = None

async def init_db():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            dsn=os.environ["DATABASE_URL"],  # must be set
            min_size=1,
            max_size=5,
            command_timeout=60
        )
        print("✅ Database pool initialized")

async def fetchrow(query, *args):
    global pool
    if pool is None:
        raise RuntimeError("Database pool not initialized!")
    async with pool.acquire() as con:
        return await con.fetchrow(query, *args)

async def fetch(query, *args):
    global pool
    if pool is None:
        raise RuntimeError("Database pool not initialized!")
    async with pool.acquire() as con:
        return await con.fetch(query, *args)

async def execute(query, *args):
    global pool
    if pool is None:
        raise RuntimeError("Database pool not initialized!")
    async with pool.acquire() as con:
        return await con.execute(query, *args)
