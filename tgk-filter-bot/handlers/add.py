from telethon import events, Button
from database.manager import Database
from services.auth import check_channel_limit
from services.channel import add_channel_flow

async def add_channel_handler(event, bot_client, user_client):
    user_id = event.sender_id
    if not await check_channel_limit(user_id):
        await event.reply("❌ Лимит исчерпан! Прокачай аккаунт через /premium 💎")
        return

    await add_channel_flow(event, bot_client, user_client)
