import asyncpg, asyncio, uuid, logging
from datetime import datetime, timedelta
from telethon import TelegramClient, events, Button, types
from telethon.tl import functions
from telethon.errors import ChannelInvalidError, ChannelPrivateError
from telethon.tl.types import BotCommand, BotCommandScopeDefault, ChannelParticipantsAdmins
from telethon.tl.functions.channels import JoinChannelRequest, GetFullChannelRequest, GetParticipantsRequest

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
api_id = 
api_hash = ""
user_phone = "+"
bot_token = ""

# PostgreSQL configuration
DB_CONFIG = {
    "user": "",
    "password": "",
    "database": "",
    "host": "localhost",
    "port": "5432",
    "min_size": 20,
    "max_size": 100,
    "max_inactive_connection_lifetime": 300,
    "command_timeout": 60
}

class Database:
    _pool = None
    
    @classmethod
    async def get_pool(cls):
        if not cls._pool:
            cls._pool = await asyncpg.create_pool(**DB_CONFIG)
            logger.info("Database connection pool created")
        return cls._pool
    
    @classmethod
    async def close_pool(cls):
        if cls._pool:
            await cls._pool.close()
            logger.info("Database connection pool closed")

# Initialize clients
user_client = TelegramClient("user_session", api_id, api_hash)
bot_client = TelegramClient("bot_session", api_id, api_hash).start(bot_token=bot_token)

# Async queue
task_queue = asyncio.Queue()

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

async def get_user_status(user_id):
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("""
            SELECT expiry_date 
            FROM users 
            WHERE user_id = $1
        """, user_id)
        return row['expiry_date'] if row else None

async def check_channel_limit(user_id):
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        count = await conn.fetchval("""
            SELECT COUNT(*) 
            FROM user_channels 
            WHERE user_id = $1
        """, user_id)
        
        expiry_date = await conn.fetchval("""
            SELECT expiry_date 
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        return expiry_date and expiry_date > datetime.now() or count < 3

async def worker():
    while True:
        try:
            task = await task_queue.get()
            await send_message_task(**task)
        except Exception as e:
            logger.error(f"Task failed: {str(e)}", exc_info=True)
        finally:
            task_queue.task_done()

async def start_workers():
    for _ in range(10):
        asyncio.create_task(worker())


@bot_client.on(events.NewMessage(pattern='/start'))
async def start_handler(event):
    user = await event.get_sender()
    referrer_id = None
    is_new_user = False
    
    # استخراج الـ referral ID من الرسالة
    if event.raw_text.startswith('/start'):
        parts = event.raw_text.split()
        if len(parts) > 1 and parts[1].isdigit():
            referrer_id = int(parts[1])
    
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        # التحقق مما إذا كان المستخدم موجود مسبقًا
        existing_user = await conn.fetchval(
            "SELECT 1 FROM users WHERE user_id = $1",
            event.sender_id
        )
        
        if not existing_user:
            is_new_user = True
            # إضافة المستخدم الجديد
            await conn.execute("""
                INSERT INTO users (user_id, username)
                VALUES ($1, $2)
            """, event.sender_id, user.username or '')
            
            # زيادة عدد المدعوين للمُحيل إن كان موجودًا
            if referrer_id and referrer_id != event.sender_id:
                await conn.execute("""
                    UPDATE users 
                    SET invited = invited + 1 
                    WHERE user_id = $1
                """, referrer_id)
        
        else:
            # تحديث اليوزرنيم إذا تغير
            await conn.execute("""
                UPDATE users 
                SET username = $2 
                WHERE user_id = $1
            """, event.sender_id, user.username or '')
    
    # بناء رسالة الترحيب
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

async def verify_channel_admin(user_id, target_channel):
    try:
        channel_entity = await user_client.get_entity(target_channel)
        
        participants = await user_client(GetParticipantsRequest(
            channel=channel_entity,
            filter=ChannelParticipantsAdmins(),
            offset=0,
            limit=100,
            hash=0
        ))
        
        for user in participants.users:
            if user.id == user_id:
                return True
        return False
        
    except ChannelPrivateError:
        return False
    except Exception as e:
        logging.error(f"Ошибка проверки прав: {str(e)}")
        return False

@bot_client.on(events.NewMessage(pattern='/add'))
async def add_channel_handler(event):
    user_id = event.sender_id
    if not await check_channel_limit(user_id):
        await event.reply("❌ Лимит исчерпан! Прокачай аккаунт через /premium 💎")
        return

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
                """, user_id, channel_id)

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
                expiry_date = await get_user_status(user_id)
                if expiry_date and expiry_date > datetime.now():
                    buttons = [
                        [Button.inline('Ко мне', b'target_self')],
                        [Button.inline('Выбрать канал', b'target_custom')]
                    ]
                    msg = await conv.send_message("🎯 Куда пересылать посты?", buttons=buttons)
                    
                    choice = await conv.wait_event(events.CallbackQuery(
                        func=lambda e: e.sender_id == user_id
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
                            
                        is_admin = await verify_channel_admin(user_id, target)
                        if not is_admin:
                            await conv.send_message("❌ Ты должен быть админом в целевом канале!")
                            await conv.cancel()
                            return

                await conn.execute("""
                    INSERT INTO user_channels (user_id, channel_id, priority)
                    VALUES ($1, $2, 1)
                    ON CONFLICT (user_id, channel_id) DO NOTHING
                """, user_id, channel_id)

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
                        """, user_id, keyword_id, target)
                        
                # إعادة ترتيب الأولويات بعد الإضافة
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
            await conv.send_message(f"✅ Канал @{channel_username} успешно добавлен! 🎉")

        except asyncio.CancelledError:
            await event.delete()
            await event.respond("🚫 Операция отменена")
        except asyncio.TimeoutError:
            await event.respond("⏰ Время вышло! Прошло 60 секунд без ответа")
        except Exception as e:
            await conv.send_message(f"❌ Неожиданная ошибка: {str(e)}")
            logger.error(f"Add Error: {str(e)}", exc_info=True)

@bot_client.on(events.CallbackQuery(pattern=b'back_to_channels_'))
async def back_to_channels_handler(event):
    try:
        await event.delete()
        class FakeEvent:
            sender_id = int(event.data.decode().split('_')[-1])
            chat_id = event.chat_id
            client = event.client
            
            async def respond(self, *args, **kwargs):
                return await event.respond(*args, **kwargs)
        
        fake_event = FakeEvent()
        await edit_handler(fake_event)
    except Exception as e:
        logger.error(f"Ошибка возврата: {str(e)}")
        await event.respond("❌ Не удалось вернуться! Попробуй /edit снова")

@bot_client.on(events.NewMessage(pattern='/edit'))
async def edit_handler(event):
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
                await show_channel_dashboard(conv, channel_id, event.sender_id)

            except asyncio.TimeoutError:
                await msg.delete()
                await event.respond("⏰ Время вышло! Прошло 60 секунд без ответа")

        except Exception as e:
            await conv.send_message(f"❌ Ошибка: {str(e)}")
            logger.error(f"Edit Handler Error: {str(e)}")

@bot_client.on(events.CallbackQuery(data=b"cancel_edit"))
async def cancel_edit_handler(event):
    try:
        await event.delete()
    except Exception as e:
        logger.error(f"❌ Не удалось отменить! : {str(e)}")

@bot_client.on(events.CallbackQuery(pattern=b'delete_keyword_'))
async def delete_keyword_handler(event):
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
                await show_channel_dashboard(conv, channel_id, event.sender_id)

    except Exception as e:
        logger.error(f"خطأ في حذف الكلمة: {str(e)}")
        await event.client.send_message(event.sender_id, "❌ Не удалось удалить! Попробуй снова. 🔄")

@bot_client.on(events.CallbackQuery(pattern=b'add_keyword_'))
async def add_keyword_handler(event):
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
                        
                        is_admin = await verify_channel_admin(user_id, target_input)
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
            await show_channel_dashboard(conv, channel_id, user_id)
        
    except Exception as e:
        logger.error(f"خطأ في إضافة الكلمة: {str(e)}")
        await event.client.send_message(user_id, "❌ Ошибка добавления! Попробуй снова. 🔄")

async def show_channel_dashboard(conv, channel_id, user_id):
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


@bot_client.on(events.CallbackQuery(pattern=b'delete_channel_'))
async def delete_channel_handler(event):
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
    await edit_handler(event)

@bot_client.on(events.CallbackQuery(pattern=b'edit_target_'))
async def edit_target_handler(event):
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
            
            is_admin = await verify_channel_admin(user_id, target_input)
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
            await show_channel_dashboard(conv, channel_id, user_id)
            
    except Exception as e:
        logger.error(f"خطأ في تعديل التارجت: {str(e)}")
        await event.respond("❌ Не удалось изменить канал! Попробуй снова. 🔄")

'''
@bot_client.on(events.NewMessage(pattern='/premium'))
async def premium_handler(event):
    user_id = event.sender_id
    pool = await Database.get_pool()
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT expiry_date 
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        if not user:
            return await event.reply("❌ User not found!")

        if not user['expiry_date'] or user['expiry_date'] < datetime.now():
            buttons = [
                [Button.url('اشتراك شهري (16 رقم)', f't.me/TF_UPGRADE_BOT?start={user_id}')]
            ]
            await event.reply("""
✨ خطة البرايم:
- مراقبة عدد غير محدود من القنوات
- إرسال إلى قنوات أخرى
- أولوية في الدعم

اختر مدة الاشتراك:
            """, buttons=buttons)
        
        else:
            remaining_days = (user['expiry_date'] - datetime.now()).days
            if remaining_days < 0:
                remaining_days = 0
            
            buttons = [
                [Button.url('✅ تأكيد التمديد', f't.me/TGK_FLTR_bot?start={user_id}')],
                [Button.inline('❌ إلغاء', b'cancel_extend')]
            ]
            
            await event.reply(
                f"⚠️ أنت مشترك بالفعل!\n"
                f"تبقى {remaining_days} يوم على انتهاء اشتراكك.\n"
                "إذا مددت الآن، سيتم إضافة 30 يوم من تاريخ اليوم.",
                buttons=buttons
            )
'''
@bot_client.on(events.NewMessage(pattern='/premium'))
async def premium_handler(event):
    user_id = event.sender_id
    pool = await Database.get_pool()
    
    async with pool.acquire() as conn:
        user = await conn.fetchrow("""
            SELECT invited, expiry_date 
            FROM users 
            WHERE user_id = $1
        """, user_id)
        
        if not user:
            return await event.reply("❌ User not found!")
        
        invited_count = user['invited']
        expiry_date = user['expiry_date']
        
        # إذا كان عدد المدعوين غير كافٍ
        if invited_count < 4:
            remaining = 4 - invited_count
            referral_link = f"t.me/@TGK_FLTR_bot?start={user_id}"
            
            await event.reply(
                f"⚠️ Тебе нужно пригласить еще {remaining} человек для Премиума! 🔗\n\n"
                f"Твоя ссылка приглашений:\n`{referral_link}`\n\n"
                "1. Отправь эту ссылку друзьям:\n"
                "2. Когда они нажмут на ссылку и запустят бота — "
                f"твой счётчик приглашений обновится!\n\n"
                f"✅ Сейчас у тебя: **{invited_count}/4**\n\n"
                "🔥 После 4 приглашений: /premium ещё раз! 💎",
                parse_mode='md'
            )
        
        # إذا كانت الدعوات كافية
        else:
            new_expiry = datetime.now() + timedelta(days=30)
            await conn.execute("""
                UPDATE users 
                SET 
                    expiry_date = $2,
                    invited = invited - 4 
                WHERE user_id = $1
            """, user_id, new_expiry)
            
            await event.reply(
                "🎉 Ты теперь Премиум! 🚀\n"
                f"Срок действия: до {new_expiry.strftime('%d.%m.%Y %H:%M')}\n"
                "Теперь можно добавлять неограниченное число каналов! 🔥"
            )

@bot_client.on(events.CallbackQuery(data=b'cancel_extend'))
async def cancel_extend_handler(event):
    await event.delete()



@bot_client.on(events.NewMessage(pattern='/help'))
async def help_handler(event):
    help_text = """
🔄 /help - Пока не готов

🔥 FUCK Миша!! ♾️

❓ **Остались вопросы?**  
📩 Пиши сюда: @HENDAW1
"""

    await event.reply(help_text, parse_mode='md', link_preview=False)



@user_client.on(events.NewMessage)
async def user_message_handler(event):
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
                                f"Источник: @{channel_username}\n\n"
                                f"⚠️ Твой Премиум истек! Сообщение отправлено тебе напрямую а не в {target} .\n"
                                f"Чтобы пересылать в {target}, обнови статус через /premium 🛒"
                            )
                            await bot_client.send_message(
                                entity=f"@{username}",
                                message=warning_msg
                            )
                        else:
                            await task_queue.put({
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

async def send_message_task(target, event, keyword, channel_username):
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

async def main():
    await Database.get_pool()  # Initialize pool
    await start_workers()
    await user_client.start(user_phone)
    await set_bot_commands()
    logger.info("User client started")
    asyncio.create_task(check_expiries())
    await bot_client.run_until_disconnected()
    await Database.close_pool()  # Close pool on shutdown

if __name__ == "__main__":
    user_client.loop.run_until_complete(main())
