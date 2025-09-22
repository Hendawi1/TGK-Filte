from telethon import events, Button
from database.manager import Database
from datetime import datetime

async def start_handler(event, bot_client):
    user = await event.get_sender()
    referrer_id = None
    is_new_user = False
    
    # Extract referral ID from message
    if event.raw_text.startswith('/start'):
        parts = event.raw_text.split()
        if len(parts) > 1 and parts[1].isdigit():
            referrer_id = int(parts[1])
    
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        # Check if user exists
        existing_user = await conn.fetchval(
            "SELECT 1 FROM users WHERE user_id = $1",
            event.sender_id
        )
        
        if not existing_user:
            is_new_user = True
            # Add new user
            await conn.execute("""
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
            """, event.sender_id, user.username or '')
            
            # Increase referrer's invite count if exists
            if referrer_id and referrer_id != event.sender_id:
                await conn.execute("""
                    UPDATE users 
                    SET invited = invited + 1 
                    WHERE user_id = $1
                """, referrer_id)
        
        else:
            # Update username if changed
            await conn.execute("""
                UPDATE users 
                SET username = $2 
                WHERE user_id = $1
            """, event.sender_id, user.username or '')
    
    # Build welcome message
    welcome_msg = """
🇷🇺 Добро пожаловать в TGK FILTER!

📢 Ты устал от бесконечных постов в каналах? 
🤖 Со мной ты будешь получать ТОЛЬКО то, что тебя интересует!

🔥 Как это работает:
1- Добавь канал через /add
2- Укажи ключевые слова
3- Буду мониторить посты и присылать тебе те, которые содержат твои ключевые слова

📌 Основные команды:
/add - Добавить канал для мониторинга
/edit - Настроить ключевые слова
/premium - Получить VIP-статус
/help - Помощь и инструкции

💎 Премиум дает:
- Неограниченное количество каналов
- Возможность пересылки постов в твой канал
- Отключение рекламы
"""
    
    await event.reply(welcome_msg)
