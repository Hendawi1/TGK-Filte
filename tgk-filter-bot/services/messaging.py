import asyncio
import logging
from datetime import datetime
from telethon import events
from database.manager import Database
from tasks.queue import task_queue

logger = logging.getLogger(__name__)

async def user_message_handler(event, user_client, bot_client):
    try:
        channel = await event.get_chat()
        
        if not channel.username:
            return

        msg_text = event.message.text.lower() if event.message.text else ""
        
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            records = await conn.fetch("""
                SELECT 
                    k.keyword_text,
                    uk.target_channel,
                    uc.priority,
                    u.expiry_date,
                    u.username
                FROM keywords k
                JOIN user_keywords uk ON k.keyword_id = uk.keyword_id
                JOIN user_channels uc ON uc.channel_id = k.channel_id AND uc.user_id = uk.user_id
                JOIN users u ON uc.user_id = u.user_id
                JOIN channels c ON k.channel_id = c.channel_id
                WHERE c.channel_username = $1
            """, channel.username)
    
        for keyword, target, priority, expiry_date, username in records:
            if keyword in msg_text:
                current_time = datetime.now()
                user_target = f"@{username}" if username else "User"
                
                if expiry_date is None or expiry_date > current_time:
                    await task_queue.put({
                        "bot_client": bot_client,
                        "target": target,
                        "event": event,
                        "keyword": keyword,
                        "channel_username": channel.username
                    })
                else:
                    if priority < 4:
                        if target.lower() != f"@{username}".lower():
                            warning_msg = (
                                f"📨 Сообщение с ключевым словом: «{keyword}»\n"
                                f"Источник: @{channel.username}\n\n"
                                f"⚠️ Твой Премиум истек! Сообщение отправлено тебе напрямую а не в {target} .\n"
                                f"Чтобы пересылать в {target}, обнови статус через /premium 🛒"
                            )
                            await bot_client.send_message(
                                entity=f"@{username}",
                                message=warning_msg
                            )
                        else:
                            await task_queue.put({
                                "bot_client": bot_client,
                                "target": target,
                                "event": event,
                                "keyword": keyword,
                                "channel_username": channel.username
                            })
                    else:
                        warning_msg = (
                            f"🔔 Обнаружено ключевое слово: {keyword}\n"
                            "❌ Пересылка невозможна! Премиум-статус истек.\n"
                            "Обнови через /premium 🛒"
                        )
                        await bot_client.send_message(
                            entity=f"@{username}",
                            message=warning_msg
                        )

    except Exception as e:
        logger.error(f"Message handling error: {str(e)}")

async def send_message_task(bot_client, target, event, keyword, channel_username):
    try:
        if isinstance(event, dict):
            event = types.Message(**event)
        
        message = f"{event.text}\n\nSource: @{channel_username}"
        
        if target.startswith('@'):
            try:
                await bot_client.send_message(
                    entity=target,
                    message=message,
                )
                logger.info(f"Sent to {target} for keyword {keyword}")
            except Exception as e:
                logger.error(f"Failed to send to {target}: {str(e)}")
        else:
            logger.warning(f"Invalid target format: {target}")

    except Exception as e:
        logger.error(f"Failed to process message: {str(e)}")
