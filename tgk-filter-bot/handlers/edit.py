from telethon import events, Button
from database.manager import Database
from services.channel import edit_channel_flow

async def edit_handler(event, bot_client):
    await edit_channel_flow(event, bot_client)
