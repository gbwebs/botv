from db.database import execute

async def clear_users_table():
    await execute("TRUNCATE TABLE users RESTART IDENTITY")
