import asyncio
import logging
from telethon import Button, types
from telethon import events
from telethon.tl import types
from telethon.tl import functions
from telethon.errors import ChannelInvalidError, ChannelPrivateError
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest
from telethon.tl.types import ChannelParticipantsAdmins
from telethon.tl.functions.channels import GetParticipantsRequest
from datetime import datetime
from database.manager import Database
from utils.validators import verify_channel_admin
from utils.helpers import show_channel_dashboard
from services.auth import get_user_status

logger = logging.getLogger(__name__)

async def add_channel_flow(event, bot_client, user_client):
    async with bot_client.conversation(event.chat_id) as conv:
        try:
            user = await event.get_sender()
            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                await conn.execute("""
                    INSERT INTO users (user_id, username)
                    VALUES ($1, $2)
                    ON CONFLICT (user_id) 
                    DO UPDATE SET username = EXCLUDED.username
                """, event.sender_id, user.username or '')
            
            if not user.username:
                await conv.send_message("❌ Для использования бота необходим юзернейм!\n"
                            "Зайди в настройки Telegram → Изменить профиль → Юзернейм\n"
                            "и установи его! 🔧")
                return

            await conv.send_message("📢 Отправь юзернейм канала с @ (Пример: @channel):")
            channel_response = await conv.get_response(timeout=60)
            channel_input = channel_response.text.strip()
            
            if any(s in channel_input.lower() for s in ['http://', 'https://', 't.me/']):
                await conv.send_message("❌ Укажи юзернейм, а не ссылку!\nПример: @channel")
                await conv.cancel()
                return

            if not channel_input.startswith('@'):
                await conv.send_message("⚡ Юзернейм должен начинаться с @!")
                await conv.cancel()
                return

            channel_username = channel_input.lstrip('@')

            try:
                entity = await user_client.get_entity(channel_username)
                await user_client(JoinChannelRequest(entity))
                
                full_channel = await user_client(GetFullChannelRequest(entity))
                channel_id = full_channel.full_chat.id
                channel_title = full_channel.chats[0].title
                
                if channel_id < 0:
                    channel_id = channel_id * -1

            except (ValueError, ChannelInvalidError, ChannelPrivateError) as e:
                error_messages = {
                    'ValueError': 'Канал не найден! 🔎',
                    'ChannelInvalidError': 'Некорректный юзернейм! 🚫',
                    'ChannelPrivateError': 'Это приватный канал! 🔒'
                }
                error_type = type(e).__name__
                await conv.send_message(f"❌ {error_messages.get(error_type, 'Неизвестная ошибка!')}")
                await conv.cancel()
                return

            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                existing_channel = await conn.fetchrow("""
                    SELECT channel_id FROM channels 
                    WHERE channel_id = $1
                """, channel_id)

                if not existing_channel:
                    await conn.execute("""
                        INSERT INTO channels (channel_id, channel_username, channel_name)
                        VALUES ($1, $2, $3)
                    """, channel_id, channel_username, channel_title)

                existing_user_channel = await conn.fetchval("""
                    SELECT 1 FROM user_channels 
                    WHERE user_id = $1 AND channel_id = $2
                """, event.sender_id, channel_id)

                if existing_user_channel:
                    await conv.send_message("⚠️ Этот канал уже добавлен! Используй /edit для изменений")
                    return

                await conv.send_message("🔑 Введи ключевые слова через запятую:")
                keywords_response = await conv.get_response(timeout=60)
                keywords = [k.strip().lower() for k in keywords_response.text.split(',') if k.strip()]
                
                if not keywords:
                    await conv.send_message("❌ Нужно минимум 1 ключевое слово!")
                    await conv.cancel()
                    return

                target = f"@{user.username}"
                expiry_date = await get_user_status(event.sender_id)
                if expiry_date and expiry_date > datetime.now():
                    buttons = [
                        [Button.inline('Ко мне', b'target_self')],
                        [Button.inline('Выбрать канал', b'target_custom')]
                    ]
                    msg = await conv.send_message("🎯 Куда пересылать посты?", buttons=buttons)
                    
                    choice = await conv.wait_event(events.CallbackQuery(
                        func=lambda e: e.sender_id == event.sender_id
                    ))
                    await msg.delete()
                    
                    if choice.data == b'target_self':
                        target = f"@{user.username}"
                    else:
                        await conv.send_message("📤 Введи юзернейм целевого канала с @:")
                        target_input = (await conv.get_response(timeout=60)).text.strip()
        
                        target_username = target_input.lstrip('@').lower()
                        if target_username == channel_username.lower():
                            await conv.send_message("❌ Нельзя выбрать тот же канал!")
                            await conv.cancel()
                            return
            
                        target = target_input
                        
                        try:
                            test_msg = await bot_client.send_message(target, "🔐 Проверяем доступы...")
                            await test_msg.delete()
                        except Exception as e:
                            await conv.send_message(
                                f"❌ Ошибка отправки в {target}!\n"
                                "Проверь:\n1. Бот добавлен как админ\n2. Есть право отправки сообщений"
                            )
                            await conv.cancel()
                            return
                            
                        is_admin = await verify_channel_admin(event.sender_id, target, user_client)
                        if not is_admin:
                            await conv.send_message("❌ Ты должен быть админом в целевом канале!")
                            await conv.cancel()
                            return

                await conn.execute("""
                    INSERT INTO user_channels (user_id, channel_id, priority)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, channel_id) DO NOTHING
                """, event.sender_id, channel_id)

                for keyword in keywords:
                    keyword_id = await conn.fetchval("""
                        INSERT INTO keywords (channel_id, keyword_text)
                        VALUES ($1, $2)
                        ON CONFLICT (channel_id, keyword_text) DO NOTHING
                        RETURNING keyword_id
                    """, channel_id, keyword)
                    
                    if keyword_id:
                        await conn.execute("""
                            INSERT INTO user_keywords (user_id, keyword_id, target_channel)
                            VALUES ($1, $2, $3)
                            ON CONFLICT (user_id, keyword_id) DO UPDATE 
                            SET target_channel = EXCLUDED.target_channel
                        """, event.sender_id, keyword_id, target)
                        
                # Reorder priorities after adding
                await conn.execute("""
                    WITH ordered_channels AS (
                        SELECT 
                            user_id, 
                            channel_id,
                            ROW_NUMBER() OVER (ORDER BY add_date ASC) as new_priority
                        FROM user_channels
                        WHERE user_id = $1
                    )
                    UPDATE user_channels uc
                    SET priority = oc.new_priority
                    FROM ordered_channels oc
                    WHERE uc.user_id = oc.user_id 
                    AND uc.channel_id = oc.channel_id
                """, event.sender_id)
            await conv.send_message(f"✅ Канал @{channel_username} успешно добавлен! 🎉")

        except asyncio.CancelledError:
            await event.delete()
            await event.respond("🚫 Операция отменена")
        except asyncio.TimeoutError:
            await event.respond("⏰ Время вышло! Прошло 60 секунд без ответа")
        except Exception as e:
            await conv.send_message(f"❌ Неожиданная ошибка: {str(e)}")
            logger.error(f"Add Error: {str(e)}", exc_info=True)

async def edit_channel_flow(event, bot_client):
    async with bot_client.conversation(event.chat_id) as conv:
        try:
            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                channels = await conn.fetch("""
                    SELECT c.channel_id, c.channel_username 
                    FROM user_channels uc
                    JOIN channels c ON uc.channel_id = c.channel_id
                    WHERE uc.user_id = $1
                """, event.sender_id)

            if not channels:
                await event.reply("❌ Нет добавленных каналов! Используй /add")
                return

            buttons = []
            for channel in channels:
                buttons.append([
                    Button.inline(f"@{channel['channel_username']}", f"edit_channel_{channel['channel_id']}")
                ])
            buttons.append([Button.inline("❌ Отмена", b"cancel_edit")])
            msg = await conv.send_message("🔧 Выбери канал для редактирования", buttons=buttons)

            try:
                response = await conv.wait_event(
                    events.CallbackQuery(
                        func=lambda e: e.sender_id == event.sender_id
                    ),
                    timeout=59
                )

                if response.data == b"cancel_edit":
                    await msg.delete()
                    return

                await msg.delete()
                channel_id = int(response.data.decode().split('_')[-1])
                await show_channel_dashboard(conv, channel_id, event.sender_id, bot_client)

            except asyncio.TimeoutError:
                await msg.delete()
                await event.respond("⏰ Время вышло! Прошло 60 секунд без ответа")

        except Exception as e:
            await conv.send_message(f"❌ Ошибка: {str(e)}")
            logger.error(f"Edit Handler Error: {str(e)}")

async def back_to_channels_handler(event, bot_client):
    try:
        await event.delete()
        user_id = int(event.data.decode().split('_')[-1])
        
        class FakeEvent:
            def __init__(self, user_id, chat_id, client):
                self.sender_id = user_id
                self.chat_id = chat_id
                self.client = client
                self.respond = self.reply
       
            async def reply(self, *args, **kwargs):
                return await self.client.send_message(self.chat_id, *args, **kwargs)
       
            async def respond(self, *args, **kwargs):
                return await self.reply(*args, **kwargs)
        
        fake_event = FakeEvent(user_id, event.chat_id, bot_client)
        await edit_channel_flow(fake_event, bot_client)
    except Exception as e:
        logger.error(f"Ошибка возврата: {str(e)}")
        await event.respond("❌ Не удалось вернуться! Попробуй /edit снова")

async def delete_keyword_handler(event, bot_client):
    try:
        parts = event.data.decode().split('_')
        channel_id = int(parts[2])
        keyword_id = int(parts[3])

        await event.delete()

        pool = await Database.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM user_keywords 
                WHERE user_id = $1 AND keyword_id = $2
            """, event.sender_id, keyword_id)

            confirmation_msg = await event.client.send_message(
                event.sender_id,
                "✅ Ключевое слово удалено! 🗑️"
            )
            
            await asyncio.sleep(1)
            async with event.client.conversation(event.sender_id) as conv:
                await show_channel_dashboard(conv, channel_id, event.sender_id, bot_client)

    except Exception as e:
        logger.error(f"خطأ في حذف الكلمة: {str(e)}")
        await event.client.send_message(event.sender_id, "❌ Не удалось удалить! Попробуй снова. 🔄")

async def add_keyword_handler(event, bot_client):
    try:
        channel_id = int(event.data.decode().split('_')[-1])
        user_id = event.sender_id
        
        await event.delete()
        
        async with event.client.conversation(user_id) as conv:
            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                monitored_channel = await conn.fetchrow("""
                    SELECT channel_username FROM channels WHERE channel_id = $1
                """, channel_id)
        
            monitored_username = monitored_channel['channel_username']
            
            await conv.send_message("🔑 Введи новое ключевое слово:")
            response = await conv.get_response()
            new_keyword = response.text.strip().lower()
            
            if not new_keyword:
                await conv.send_message("❌ Ключевое слово не может быть пустым! ⚠️")
                return
            
            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                existing = await conn.fetchval("""
                    SELECT 1 
                    FROM user_keywords uk
                    JOIN keywords k ON uk.keyword_id = k.keyword_id
                    WHERE uk.user_id = $1 
                    AND k.channel_id = $2 
                    AND k.keyword_text = $3
                """, user_id, channel_id, new_keyword)
                
                if existing:
                    await conv.send_message("⚠️ Это слово уже есть! Используй другое. 🔄")
                    return
                
                keyword_id = await conn.fetchval("""
                    WITH insert_keyword AS (
                        INSERT INTO keywords (channel_id, keyword_text)
                        VALUES ($1, $2)
                        ON CONFLICT (channel_id, keyword_text) DO NOTHING
                        RETURNING keyword_id
                    )
                    SELECT keyword_id FROM insert_keyword
                    UNION
                    SELECT keyword_id FROM keywords 
                    WHERE channel_id = $1 AND keyword_text = $2
                    LIMIT 1
                """, channel_id, new_keyword)
                
                expiry_date = await conn.fetchval("""
                    SELECT expiry_date FROM users WHERE user_id = $1
                """, user_id)

                target = f"@{event.sender.username}"
                if expiry_date and expiry_date > datetime.now():
                    buttons = [
                        [Button.inline('Ко мне', b'target_self')],
                        [Button.inline('Выбрать канал', b'target_custom')]
                    ]
                    msg = await conv.send_message("Choose target channel:", buttons=buttons)
                    choice = await conv.wait_event(events.CallbackQuery)
                    await msg.delete()
                    
                    if choice.data == b'target_self':
                        target = f"@{event.sender.username}"
                    else:
                        await conv.send_message("📤 Введи юзернейм целевого канала с @:")
                        target_input = (await conv.get_response()).text.strip()
                        
                        if any(s in target_input.lower() for s in ['http://', 'https://', 't.me/']):
                            await conv.send_message("❌ Укажи юзернейм, а не ссылку! 🔗")
                            await conv.cancel()
                            return

                        if target_input.lstrip('@').lower() == monitored_username.lower():
                            await conv.send_message("❌ Нельзя выбрать тот же канал! 🔄")
                            return
                        
                        try:
                            test_msg = await bot_client.send_message(
                                entity=target_input,
                                message="🔒 Bot permission check (this message will be deleted)"
                            )
                            await test_msg.delete()
                        except Exception as e:
                            await conv.send_message(
                f"❌ Ошибка отправки в {target_input}!\n"
                "Проверь:\n"
                "1. Бот добавлен как админ 👨💻\n"
                "2. Есть право отправки сообщений 📩\n"
                "3. Канал не закрыт 🔓"
            )
                            return
                        
                        is_admin = await verify_channel_admin(user_id, target_input, bot_client)
                        if not is_admin:
                            await conv.send_message("❌ Ты должен быть админом канала! 👮♂️")
                            return
                        
                        target = target_input
                
                await conn.execute("""
                    INSERT INTO user_keywords (user_id, keyword_id, target_channel)
                    VALUES ($1, $2, $3)
                    ON CONFLICT (user_id, keyword_id) DO UPDATE 
                    SET target_channel = EXCLUDED.target_channel
                """, user_id, keyword_id, target)
        
            confirmation_msg = await conv.send_message(f"✅ Ключевое слово «{new_keyword}» добавлено! 🎉")
            await asyncio.sleep(1)
            await show_channel_dashboard(conv, channel_id, user_id, bot_client)
        
    except Exception as e:
        logger.error(f"خطأ في إضافة الكلمة: {str(e)}")
        await event.client.send_message(user_id, "❌ Ошибка добавления! Попробуй снова. 🔄")

async def delete_channel_handler(event, bot_client):
    channel_id = int(event.data.decode().split('_')[-1])
    user_id = event.sender_id
    
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        await conn.execute("""
            DELETE FROM user_keywords 
            USING keywords 
            WHERE user_keywords.keyword_id = keywords.keyword_id
            AND user_keywords.user_id = $1
            AND keywords.channel_id = $2
        """, user_id, channel_id)
        
        await conn.execute("""
            DELETE FROM keywords 
            WHERE channel_id = $1
            AND keyword_id NOT IN (
                SELECT keyword_id FROM user_keywords
            )
        """, channel_id)
        
        await conn.execute("""
            DELETE FROM user_channels 
            WHERE user_id = $1 AND channel_id = $2
        """, user_id, channel_id)
        
        await conn.execute("""
            WITH ordered_channels AS (
                SELECT 
                    user_id, 
                    channel_id,
                    ROW_NUMBER() OVER (ORDER BY add_date ASC) as new_priority
                FROM user_channels
                WHERE user_id = $1
            )
            UPDATE user_channels uc
            SET priority = oc.new_priority
            FROM ordered_channels oc
            WHERE uc.user_id = oc.user_id 
            AND uc.channel_id = oc.channel_id
        """, user_id)

    await event.delete()
    await event.respond("✅ Канал удален! 🗑️")
    


async def edit_target_handler(event, bot_client):
    try:
        parts = event.data.decode().split('_')
        channel_id = int(parts[2])
        keyword_id = int(parts[3])
        user_id = event.sender_id
        
        async with bot_client.conversation(user_id) as conv:
            await event.delete()
            
            pool = await Database.get_pool()
            async with pool.acquire() as conn:
                monitored_channel = await conn.fetchrow("""
                    SELECT channel_username FROM channels WHERE channel_id = $1
                """, channel_id)
                current_target = await conn.fetchval("""
                    SELECT target_channel FROM user_keywords 
                    WHERE user_id = $1 AND keyword_id = $2
                """, user_id, keyword_id)
        
            monitored_username = monitored_channel['channel_username']
            
            await conv.send_message(f"📤 Введи юзернейм нового целевого канала с @:")
            target_input = (await conv.get_response()).text.strip()
            
            target_username = target_input.lstrip('@').lower()
            if any(s in target_input.lower() for s in ['http://', 'https://', 't.me/']):
                await conv.send_message("❌ Укажи юзернейм, а не ссылку! 🔗")
                await conv.cancel()
                return
            
            if target_username == monitored_username.lower():
                await conv.send_message("❌ Нельзя выбрать тот же канал!")
                return
            
            try:
                test_msg = await bot_client.send_message(
                    entity=target_input,
                    message="🔒 Bot permission check (this message will be deleted)"
                )
                await test_msg.delete()
            except Exception as e:
                await conv.send_message(
                f"❌ Ошибка отправки в {target_input}!\n"
                "Проверь:\n"
                "1. Бот добавлен как админ 👨💻\n"
                "2. Есть право отправки сообщений 📩\n"
                "3. Канал не закрыт 🔓"
            )
                return
            
            is_admin = await verify_channel_admin(user_id, target_input, bot_client)
            if not is_admin:
                await conv.send_message("❌ Ты должен быть админом канала! 👮♂️")
                return
            
            async with pool.acquire() as conn:
                await conn.execute("""
                    UPDATE user_keywords 
                    SET target_channel = $1
                    WHERE user_id = $2 AND keyword_id = $3
                """, target_input, user_id, keyword_id)
            
            await conv.send_message(f"✅ Новый получатель: {target_input} 🎯")
            await show_channel_dashboard(conv, channel_id, user_id, bot_client)
            
    except Exception as e:
        logger.error(f"خطأ في تعديل التارجت: {str(e)}")
        await event.respond("❌ Не удалось изменить канал! Попробуй снова. 🔄")

async def cancel_edit_handler(event, bot_client):
    try:
        await event.delete()
    except Exception as e:
        logger.error(f"❌ Не удалось отменить! : {str(e)}")
