from pymongo import MongoClient
from pymongo.collection import Collection
from app.config import settings

print(f"[MONGO] Подключаемся к MongoDB: {settings.MONGO_URI}")
print(f"[MONGO] База данных: {settings.MONGO_DB}")

try:
    mongo_client = MongoClient(settings.MONGO_URI)
    print(f"[MONGO] Клиент MongoDB создан успешно")
    
    db = mongo_client.get_database(settings.MONGO_DB)
    print(f"[MONGO] Подключение к базе данных {settings.MONGO_DB} установлено")
    
    # Проверяем подключение
    mongo_client.admin.command('ping')
    print(f"[MONGO] Пинг к MongoDB успешен - соединение работает!")
    
except Exception as e:
    print(f"[MONGO] ОШИБКА подключения к MongoDB: {e}")
    raise

# Collections
try:
    users: Collection = db["users"]
    conversations: Collection = db["conversations"]
    test: Collection = db["test"]
    print(f"[MONGO] Коллекции инициализированы: users, conversations, test")
except Exception as e:
    print(f"[MONGO] ОШИБКА инициализации коллекций: {e}")
    raise