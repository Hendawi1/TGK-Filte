from telethon import events

async def help_handler(event, bot_client):
    help_text = """
🔄 /help - Пока не готов

🔥 FUCK Миша!! ♾️

❓ **Остались вопросы?**  
📩 Пиши сюда: @HENDAW1
"""

    await event.reply(help_text, parse_mode='md', link_preview=False)
