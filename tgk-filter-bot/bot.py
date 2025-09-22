import asyncio
from telethon import functions
from telethon.tl.types import BotCommand, BotCommandScopeDefault
import logging
from telethon import TelegramClient, events
from telethon.tl.types import BotCommand, BotCommandScopeDefault
from config.settings import API_ID, API_HASH, USER_PHONE, BOT_TOKEN
from database.manager import Database
from tasks.workers import start_workers, stop_workers
from handlers.start import start_handler
from handlers.add import add_channel_handler
from handlers.edit import edit_handler
from handlers.premium import premium_handler
from handlers.help import help_handler
from handlers.callbacks import setup_callbacks
from services.messaging import user_message_handler

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Initialize clients
user_client = TelegramClient("user_session", API_ID, API_HASH)
bot_client = TelegramClient("bot_session", API_ID, API_HASH).start(bot_token=BOT_TOKEN)

async def set_bot_commands():
    RU_commands = [
        BotCommand(command='add', description='➕ Добавить канал'),
        BotCommand(command='edit', description='⚙️ Настройки'),
        BotCommand(command='premium', description='💎  доступ'),
        BotCommand(command='help', description='🆘 Помощь')
    ]
    
    await bot_client(functions.bots.SetBotCommandsRequest(
        scope=BotCommandScopeDefault(),
        lang_code='',
        commands=RU_commands
    ))

async def check_expiries():
    while True:
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            users = await conn.fetch("""
                SELECT user_id 
                FROM users 
                WHERE expiry_date BETWEEN NOW() + INTERVAL '2 days' AND NOW() + INTERVAL '3 days'
            """)
            
            for user in users:
                await bot_client.send_message(
                    user['user_id'],
                    "⚠️ Твой Премиум-статус истекает через 3 дня!\n🔄 Продли через /premium"
                )
            
            await conn.execute("""
                DELETE FROM user_channels 
                WHERE user_id IN (
                    SELECT u.user_id 
                    FROM users u
                    WHERE u.expiry_date < NOW()
                )
                AND (user_id, channel_id) NOT IN (
                    SELECT uc.user_id, uc.channel_id 
                    FROM user_channels uc
                    WHERE uc.user_id = user_channels.user_id 
                    ORDER BY uc.priority 
                    LIMIT 3
                )
            """)
    
        await asyncio.sleep(86400)

# Register handlers
def register_handlers():
    bot_client.add_event_handler(
        lambda e: start_handler(e, bot_client), 
        events.NewMessage(pattern='/start')
    )
    
    bot_client.add_event_handler(
        lambda e: add_channel_handler(e, bot_client, user_client), 
        events.NewMessage(pattern='/add')
    )
    
    bot_client.add_event_handler(
        lambda e: edit_handler(e, bot_client), 
        events.NewMessage(pattern='/edit')
    )
    
    bot_client.add_event_handler(
        lambda e: premium_handler(e, bot_client), 
        events.NewMessage(pattern='/premium')
    )
    
    bot_client.add_event_handler(
        lambda e: help_handler(e, bot_client), 
        events.NewMessage(pattern='/help')
    )
    
    user_client.add_event_handler(
        lambda e: user_message_handler(e, user_client, bot_client), 
        events.NewMessage()
    )
    
    #await setup_callbacks(bot_client)

async def main():
    await Database.get_pool()
    await start_workers(bot_client)
    await user_client.start(USER_PHONE)
    await set_bot_commands()
    await setup_callbacks(bot_client)
    logger.info("User client started")
    
    register_handlers()
    
    expiry_task = asyncio.create_task(check_expiries())
    
    try:
        await bot_client.run_until_disconnected()
    finally:
        expiry_task.cancel()
        await stop_workers()
        await Database.close_pool()

if __name__ == "__main__":
    user_client.loop.run_until_complete(main())
