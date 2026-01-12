from db.database import execute

async def clear_users_table(chat_id: int):
    # delete links belonging to this chat only
    await execute(
        """
        DELETE FROM links
        WHERE user_id IN (
            SELECT id FROM users WHERE chat_id = $1
        )
        """,
        chat_id
    )

    # delete users of this chat only
    await execute(
        "DELETE FROM users WHERE chat_id = $1",
        chat_id
    )

