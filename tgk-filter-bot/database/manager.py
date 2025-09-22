import asyncpg
import logging
from config.database import get_db_config

logger = logging.getLogger(__name__)

class Database:
    _pool = None
    
    @classmethod
    async def get_pool(cls):
        if not cls._pool:
            db_config = get_db_config()
            cls._pool = await asyncpg.create_pool(**db_config)
            logger.info("Database connection pool created")
        return cls._pool
    
    @classmethod
    async def close_pool(cls):
        if cls._pool:
            await cls._pool.close()
            logger.info("Database connection pool closed")
