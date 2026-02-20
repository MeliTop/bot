import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv('8308533850:AAEVHfTxEiEB4pRMkGcx8vDkj9_4ZPO-kJo')  # Токен бота от @BotFather
ADMIN_ID = int(os.getenv('2023472445'))  # Ваш Telegram ID
GIRLFRIEND_ID = int(os.getenv('1442215588'))  # Telegram ID девушки

# ID для тестирования (замените на свои)
# ADMIN_ID = 123456789
# GIRLFRIEND_ID = 987654321