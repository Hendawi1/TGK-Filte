from telethon import Button
from database.manager import Database
from datetime import datetime

async def show_channel_dashboard(conv, channel_id, user_id, bot_client):
    try:
        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            user = await conn.fetchrow("""
                SELECT username FROM users WHERE user_id = $1
            """, user_id)
            
            if not user:
                await conv.send_message("❌ Пользователь не найден!")
                return
            
            username = user.get('username', '')
            target_default = f"@{username}" if username else ""

            channel = await conn.fetchrow("""
                SELECT c.channel_username, c.channel_name 
                FROM channels c 
                WHERE c.channel_id = $1
            """, channel_id)
            
            if not channel:
                await conv.send_message("❌ Канал не найден!")
                return
                
            channel_username = channel['channel_username']
            channel_name = channel['channel_name']

            keywords = await conn.fetch("""
                SELECT k.keyword_id, k.keyword_text, uk.target_channel 
                FROM user_keywords uk
                INNER JOIN keywords k ON uk.keyword_id = k.keyword_id
                WHERE uk.user_id = $1 
                AND k.channel_id = $2
            """, user_id, channel_id)

            buttons = []
            expiry_date = await conn.fetchval("""
                SELECT expiry_date FROM users WHERE user_id = $1
            """, user_id)
            is_premium = expiry_date and expiry_date > datetime.now()

            for keyword in keywords:
                target = keyword['target_channel'] or target_default
                if is_premium:
                    buttons.append([
                        Button.inline(f"🗑 {keyword['keyword_text']}", f"delete_keyword_{channel_id}_{keyword['keyword_id']}"),
                        Button.inline(f"🎯 {target}", f"edit_target_{channel_id}_{keyword['keyword_id']}")
                    ])
                else:
                    buttons.append([
                        Button.inline(f"🗑 {keyword['keyword_text']}", f"delete_keyword_{channel_id}_{keyword['keyword_id']}")
                    ])
                
            buttons.extend([
                [Button.inline("➕ Добавить ключевое слово", f"add_keyword_{channel_id}")],
                [
                    Button.inline("❌ Удалить канал", f"delete_channel_{channel_id}"),
                    Button.inline("🔙 Назад", f"back_to_channels_{user_id}")
                ]
            ])

            message_text = (
                f"🔧 Управление каналом: @{channel_username}\n"
                f"📌 Название: {channel_name}\n"
                "▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬\n"
                "Выбери действие:"
            )
            
            await conv.send_message(
                message_text,
                buttons=buttons
            )

    except Exception as e:
        logger.error(f"خطأ في عرض الداشبورد: {str(e)}")
        await conv.send_message("⚠️ Ошибка загрузки дашборда! Попробуй позже. 🔄")
