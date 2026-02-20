# check_db.py
from database import Session, User, Quest, Task, Submission, QuestCompletion
from sqlalchemy import text

session = Session()

print("=" * 50)
print("ПРОВЕРКА БАЗЫ ДАННЫХ")
print("=" * 50)

# Проверяем таблицы
tables = session.execute(text("SELECT name FROM sqlite_master WHERE type='table';")).fetchall()
print("\n📊 Таблицы в базе:")
for table in tables:
    count = session.execute(text(f"SELECT COUNT(*) FROM {table[0]}")).scalar()
    print(f"  • {table[0]}: {count} записей")

# Проверяем пользователей
users = session.query(User).all()
print(f"\n👥 Пользователи ({len(users)}):")
for user in users:
    print(f"  • ID: {user.id}, Telegram: {user.telegram_id}, Админ: {user.is_admin}")

# Проверяем квесты
quests = session.query(Quest).all()
print(f"\n🎯 Квесты ({len(quests)}):")
for quest in quests:
    print(f"  • {quest.title} (ID: {quest.id})")

session.close()
print("\n" + "=" * 50)