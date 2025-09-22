from datetime import datetime
from database.manager import Database

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
