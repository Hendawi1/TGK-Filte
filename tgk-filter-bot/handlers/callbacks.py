from telethon import events
from services.channel import (
    back_to_channels_handler,
    delete_keyword_handler,
    add_keyword_handler,
    delete_channel_handler,
    edit_target_handler,
    cancel_edit_handler
)

async def setup_callbacks(bot_client):
    @bot_client.on(events.CallbackQuery(pattern=b'back_to_channels_'))
    async def back_to_channels_wrapper(event):
        await back_to_channels_handler(event, bot_client)

    @bot_client.on(events.CallbackQuery(pattern=b'delete_keyword_'))
    async def delete_keyword_wrapper(event):
        await delete_keyword_handler(event, bot_client)

    @bot_client.on(events.CallbackQuery(pattern=b'add_keyword_'))
    async def add_keyword_wrapper(event):
        await add_keyword_handler(event, bot_client)

    @bot_client.on(events.CallbackQuery(pattern=b'delete_channel_'))
    async def delete_channel_wrapper(event):
        await delete_channel_handler(event, bot_client)

    @bot_client.on(events.CallbackQuery(pattern=b'edit_target_'))
    async def edit_target_wrapper(event):
        await edit_target_handler(event, bot_client)

    @bot_client.on(events.CallbackQuery(data=b'cancel_edit'))
    async def cancel_edit_wrapper(event):
        await cancel_edit_handler(event, bot_client)
