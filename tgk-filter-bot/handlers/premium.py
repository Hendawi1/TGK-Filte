from telethon import events, Button
from database.manager import Database
from datetime import datetime, timedelta

async def premium_handler(event, bot_client):
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
        
        # If not enough invites
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
        
        # If enough invites
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
