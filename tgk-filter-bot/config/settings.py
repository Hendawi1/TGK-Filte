import os

# Telegram settings
API_ID = int(os.getenv('API_ID', ''))
API_HASH = os.getenv('API_HASH', '')
USER_PHONE = os.getenv('USER_PHONE', '+')
BOT_TOKEN = os.getenv('BOT_TOKEN', '')

# Database configuration
DB_CONFIG = {
    "user": os.getenv('DB_USER', ''),
    "password": os.getenv('DB_PASSWORD', ''),
    "database": os.getenv('DB_NAME', ''),
    "host": os.getenv('DB_HOST', 'localhost'),
    "port": os.getenv('DB_PORT', '5432'),
    "min_size": int(os.getenv('DB_MIN_SIZE', 20)),
    "max_size": int(os.getenv('DB_MAX_SIZE', 100)),
    "max_inactive_connection_lifetime": float(os.getenv('DB_MAX_INACTIVE', 300)),
    "command_timeout": int(os.getenv('DB_COMMAND_TIMEOUT', 60))
}

