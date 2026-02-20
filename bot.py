import asyncio
import logging
import os
import sys
import uuid
import shutil
from datetime import datetime, date, timedelta
from pathlib import Path

from aiogram import Bot, Dispatcher, types, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import FSInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv

from database import Session, User, Quest, Task, Submission, QuestCompletion
import keyboards as nav
from utils import optimize_image, format_progress_bar, validate_date, cleanup_quest_files

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

# Проверка токена
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    logger.error("❌ Токен не найден в .env файле!")
    sys.exit(1)

try:
    ADMIN_ID = int(os.getenv('ADMIN_ID', '0'))
    GIRLFRIEND_ID = int(os.getenv('GIRLFRIEND_ID', '0'))
except ValueError:
    logger.error("❌ Ошибка в ID! Проверьте .env файл")
    sys.exit(1)

# Инициализация бота с увеличенными таймаутами
from aiogram.client.session.aiohttp import AiohttpSession

session = AiohttpSession(timeout=120)
bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML), session=session)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния FSM
class QuestCreation(StatesGroup):
    title = State()
    description = State()
    image = State()
    reward = State()
    required = State()

class TaskCreation(StatesGroup):
    quest_id = State()
    title = State()
    description = State()
    image = State()
    points = State()
    date = State()

class TaskEdit(StatesGroup):
    task_id = State()
    field = State()
    value = State()

class SubmissionStates(StatesGroup):
    waiting_for_photo = State()
    waiting_for_comment = State()
    task_id = State()
    photo_path = State()

# Вспомогательные функции
async def get_user(telegram_id: int):
    """Получить или создать пользователя"""
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=telegram_id).first()
        if not user:
            user = User(
                telegram_id=telegram_id, 
                is_admin=(telegram_id == ADMIN_ID)
            )
            session.add(user)
            session.commit()
            logger.info(f"✅ Создан пользователь {telegram_id}")
        return user
    finally:
        session.close()

async def safe_edit_message(message, text, reply_markup=None):
    """Безопасное редактирование сообщения"""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except Exception as e:
        try:
            await message.delete()
            await message.answer(text, reply_markup=reply_markup)
        except:
            pass

async def safe_delete_message(message):
    """Безопасное удаление сообщения"""
    try:
        await message.delete()
    except:
        pass

async def get_quest_by_id(quest_id: int):
    """Получить квест по ID"""
    session = Session()
    try:
        return session.query(Quest).filter(Quest.id == quest_id).first()
    finally:
        session.close()

async def get_task_by_id(task_id: int):
    """Получить задание по ID"""
    session = Session()
    try:
        return session.query(Task).filter(Task.id == task_id).first()
    finally:
        session.close()

async def download_photo_with_retry(file, dest, max_retries=3):
    """Скачать фото с повторными попытками"""
    for attempt in range(max_retries):
        try:
            download_task = asyncio.create_task(
                bot.download_file(file.file_path, dest)
            )
            await asyncio.wait_for(download_task, timeout=30)
            return True
        except asyncio.TimeoutError:
            logger.warning(f"Таймаут при скачивании фото, попытка {attempt + 1}/{max_retries}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                return False
        except Exception as e:
            logger.warning(f"Ошибка при скачивании фото: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2)
            else:
                return False
    return False

async def cleanup_task_files(task_id: int):
    """Очистить файлы задания"""
    session = Session()
    try:
        # Удаляем все фото отчетов по заданию
        submissions = session.query(Submission).filter_by(task_id=task_id).all()
        for sub in submissions:
            if sub.photo_url and os.path.exists(sub.photo_url):
                try:
                    os.remove(sub.photo_url)
                    logger.info(f"Удалено фото отчета: {sub.photo_url}")
                except Exception as e:
                    logger.error(f"Ошибка при удалении фото: {e}")
        
        # Удаляем фото самого задания
        task = session.query(Task).filter(Task.id == task_id).first()
        if task and task.image_url and os.path.exists(task.image_url):
            try:
                os.remove(task.image_url)
                logger.info(f"Удалено фото задания: {task.image_url}")
            except Exception as e:
                logger.error(f"Ошибка при удалении фото задания: {e}")
    finally:
        session.close()

async def cleanup_quest_files(quest_id: int):
    """Очистить все файлы квеста"""
    session = Session()
    try:
        # Удаляем фото всех заданий и отчетов
        tasks = session.query(Task).filter_by(quest_id=quest_id).all()
        for task in tasks:
            await cleanup_task_files(task.id)
        
        # Удаляем фото квеста
        quest = session.query(Quest).filter(Quest.id == quest_id).first()
        if quest and quest.image_url and os.path.exists(quest.image_url):
            try:
                os.remove(quest.image_url)
                logger.info(f"Удалено фото квеста: {quest.image_url}")
            except Exception as e:
                logger.error(f"Ошибка при удалении фото квеста: {e}")
    finally:
        session.close()

# Команда /start
@dp.message(CommandStart())
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    if message.from_user.id not in [ADMIN_ID, GIRLFRIEND_ID]:
        await message.answer("❌ У вас нет доступа к этому боту")
        return
    
    await get_user(message.from_user.id)
    
    welcome_text = """
🌸 <b>Квест-бот для отношений</b> 🌸

Здесь вы можете создавать увлекательные квесты и задания, 
отслеживать прогресс и получать награды!
"""
    
    if message.from_user.id == ADMIN_ID:
        await message.answer(welcome_text, reply_markup=nav.admin_main_menu())
    else:
        await message.answer(welcome_text, reply_markup=nav.girlfriend_main_menu())

# Команда /menu и /cancel
@dp.message(Command("menu"))
@dp.message(Command("cancel"))
async def cmd_menu(message: types.Message, state: FSMContext):
    """Возврат в меню"""
    await state.clear()
    await safe_delete_message(message)
    
    if message.from_user.id == ADMIN_ID:
        await message.answer("🏠 Главное меню", reply_markup=nav.admin_main_menu())
    else:
        await message.answer("🏠 Главное меню", reply_markup=nav.girlfriend_main_menu())

# Обработка callback-запросов
@dp.callback_query()
async def handle_callback(callback: types.CallbackQuery, state: FSMContext):
    """Обработка всех callback-запросов"""
    user_id = callback.from_user.id
    data = callback.data
    
    try:
        # Обработка отмены
        if data == "cancel_action":
            await state.clear()
            await safe_edit_message(
                callback.message,
                "❌ Действие отменено",
                nav.admin_main_menu() if user_id == ADMIN_ID else nav.girlfriend_main_menu()
            )
            return
        
        # Возврат в главное меню
        if data == "main_menu":
            await state.clear()
            await safe_edit_message(
                callback.message,
                "🏠 Главное меню",
                nav.admin_main_menu() if user_id == ADMIN_ID else nav.girlfriend_main_menu()
            )
            return

        # Разбираем callback_data на части
        parts = data.split('_')
        
        # АДМИН ПАНЕЛЬ
        if user_id == ADMIN_ID:
            
            # Статистика девушки
            if data == "girl_stats" or data == "refresh_stats":
                session = Session()
                try:
                    girlfriend = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
                    
                    if not girlfriend:
                        await safe_edit_message(
                            callback.message,
                            "❌ Девушка не найдена в базе",
                            nav.back_button()
                        )
                        return
                    
                    quests = session.query(Quest).filter_by(is_active=True).all()
                    submissions = session.query(Submission).filter_by(
                        user_id=girlfriend.id, is_approved=True
                    ).all()
                    
                    # Статистика по дням
                    last_7_days = []
                    today = date.today()
                    for i in range(7):
                        day = today - timedelta(days=i)
                        day_start = datetime(day.year, day.month, day.day)
                        day_end = day_start + timedelta(days=1)
                        count = session.query(Submission).filter(
                            Submission.user_id == girlfriend.id,
                            Submission.is_approved == True,
                            Submission.approved_at >= day_start,
                            Submission.approved_at < day_end
                        ).count()
                        last_7_days.append((day.strftime("%d.%m"), count))
                    
                    stats_text = f"""
📊 <b>СТАТИСТИКА ДЕВУШКИ</b> (обновлено {datetime.now().strftime('%H:%M:%S')})

👤 <b>{girlfriend.username or 'Девушка'}</b>

📅 <b>Активность за 7 дней:</b>
"""
                    for day, count in reversed(last_7_days):
                        bar = "█" * count + "░" * (5 - count)
                        stats_text += f"{day}: {bar} {count} зад.\n"
                    
                    stats_text += f"\n<b>Всего выполнено:</b> {len(submissions)} заданий\n\n"
                    stats_text += "<b>Прогресс по квестам:</b>\n"
                    
                    for quest in quests:
                        completed = session.query(Submission).join(Task).filter(
                            Task.quest_id == quest.id,
                            Submission.user_id == girlfriend.id,
                            Submission.is_approved == True
                        ).count()
                        
                        done = session.query(QuestCompletion).filter_by(
                            quest_id=quest.id, user_id=girlfriend.id
                        ).first()
                        
                        if done:
                            stats_text += f"\n✅ {quest.title} - ЗАВЕРШЁН! 🎁 {quest.reward}"
                        else:
                            bar = format_progress_bar(completed, quest.required_completions)
                            stats_text += f"\n📌 {quest.title}: {bar} {completed}/{quest.required_completions}"
                    
                    # Кнопка обновления
                    builder = InlineKeyboardBuilder()
                    builder.button(text="🔄 Обновить", callback_data="refresh_stats")
                    builder.button(text="◀️ Назад", callback_data="main_menu")
                    builder.adjust(1)
                    
                    await safe_edit_message(callback.message, stats_text, builder.as_markup())
                finally:
                    session.close()
            
            # Управление квестами
            elif data == "manage_quests":
                session = Session()
                try:
                    quests = session.query(Quest).filter_by(is_active=True).all()
                    
                    quest_list = []
                    for q in quests:
                        tasks_count = session.query(Task).filter_by(quest_id=q.id).count()
                        quest_list.append({
                            'id': q.id,
                            'title': q.title,
                            'tasks': tasks_count
                        })
                    
                    await safe_edit_message(
                        callback.message,
                        "📋 <b>Управление квестами</b>\n\nВыберите квест:",
                        nav.quest_management_menu(quest_list)
                    )
                finally:
                    session.close()
            
            # Действия с квестом
            elif len(parts) == 3 and parts[0] == "manage" and parts[1] == "quest":
                try:
                    quest_id = int(parts[2])
                    quest = await get_quest_by_id(quest_id)
                    if quest:
                        await safe_edit_message(
                            callback.message,
                            f"📌 <b>{quest.title}</b>\n\nВыберите действие:",
                            nav.quest_actions_menu(quest_id)
                        )
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Управление заданиями квеста
            elif len(parts) == 4 and parts[0] == "manage" and parts[1] == "quest" and parts[2] == "tasks":
                try:
                    quest_id = int(parts[3])
                    session = Session()
                    try:
                        tasks = session.query(Task).filter_by(quest_id=quest_id).order_by(Task.order).all()
                        quest = session.query(Quest).filter(Quest.id == quest_id).first()
                        
                        task_list = []
                        for t in tasks:
                            completed = session.query(Submission).filter_by(
                                task_id=t.id, is_approved=True
                            ).first() is not None
                            task_list.append({
                                'id': t.id,
                                'title': t.title,
                                'completed': completed
                            })
                        
                        await safe_edit_message(
                            callback.message,
                            f"📋 <b>Задания квеста '{quest.title}'</b>",
                            nav.task_management_menu(task_list, quest_id)
                        )
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[3]}")
            
            # Удаление квеста
            elif len(parts) == 3 and parts[0] == "delete" and parts[1] == "quest":
                try:
                    quest_id = int(parts[2])
                    await safe_edit_message(
                        callback.message,
                        "⚠️ <b>Вы уверены?</b>\nЭто удалит квест, все задания и все фото!",
                        nav.confirm_delete_quest(quest_id)
                    )
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Подтверждение удаления квеста
            elif len(parts) == 4 and parts[0] == "confirm" and parts[1] == "delete" and parts[2] == "quest":
                try:
                    quest_id = int(parts[3])
                    
                    # Сначала удаляем все файлы
                    await cleanup_quest_files(quest_id)
                    
                    # Потом удаляем из базы
                    session = Session()
                    try:
                        quest = session.query(Quest).filter(Quest.id == quest_id).first()
                        if quest:
                            session.delete(quest)
                            session.commit()
                            await safe_edit_message(
                                callback.message,
                                "✅ Квест и все связанные файлы удалены!",
                                nav.admin_main_menu()
                            )
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[3]}")
            
            # Редактирование задания
            elif len(parts) == 3 and parts[0] == "edit" and parts[1] == "task":
                try:
                    task_id = int(parts[2])
                    await state.update_data(task_id=task_id)
                    
                    task = await get_task_by_id(task_id)
                    if task:
                        text = f"""
📝 <b>Редактирование задания</b>

<b>Название:</b> {task.title}
<b>Описание:</b> {task.description}
<b>Очки:</b> {task.points}
<b>Дата:</b> {task.scheduled_date or 'Не указана'}

Выберите что изменить:
"""
                        await safe_edit_message(callback.message, text, nav.task_edit_menu(task_id))
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Редактирование полей
            elif len(parts) == 3 and parts[0] == "edit" and parts[1] == "title":
                try:
                    task_id = int(parts[2])
                    await state.update_data(task_id=task_id, field="title")
                    await safe_edit_message(
                        callback.message,
                        "✏️ Введите новое название задания:",
                        nav.cancel_button()
                    )
                    await state.set_state(TaskEdit.field)
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            elif len(parts) == 3 and parts[0] == "edit" and parts[1] == "desc":
                try:
                    task_id = int(parts[2])
                    await state.update_data(task_id=task_id, field="description")
                    await safe_edit_message(
                        callback.message,
                        "📝 Введите новое описание задания:",
                        nav.cancel_button()
                    )
                    await state.set_state(TaskEdit.field)
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            elif len(parts) == 3 and parts[0] == "edit" and parts[1] == "points":
                try:
                    task_id = int(parts[2])
                    await state.update_data(task_id=task_id, field="points")
                    await safe_edit_message(
                        callback.message,
                        "💰 Введите новую стоимость задания (число):",
                        nav.cancel_button()
                    )
                    await state.set_state(TaskEdit.field)
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            elif len(parts) == 3 and parts[0] == "edit" and parts[1] == "date":
                try:
                    task_id = int(parts[2])
                    await state.update_data(task_id=task_id, field="date")
                    await safe_edit_message(
                        callback.message,
                        "📅 Введите новую дату (ГГГГ-ММ-ДД) или 'нет':",
                        nav.cancel_button()
                    )
                    await state.set_state(TaskEdit.field)
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Удаление задания
            elif len(parts) == 3 and parts[0] == "delete" and parts[1] == "task":
                try:
                    task_id = int(parts[2])
                    await safe_edit_message(
                        callback.message,
                        "⚠️ <b>Вы уверены?</b>\nЭто удалит задание и все связанные фото!",
                        nav.confirm_delete_task(task_id)
                    )
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Подтверждение удаления задания
            elif len(parts) == 4 and parts[0] == "confirm" and parts[1] == "delete" and parts[2] == "task":
                try:
                    task_id = int(parts[3])
                    
                    # Сначала удаляем все файлы задания
                    await cleanup_task_files(task_id)
                    
                    # Потом удаляем из базы
                    session = Session()
                    try:
                        task = session.query(Task).filter(Task.id == task_id).first()
                        if task:
                            quest_id = task.quest_id
                            session.delete(task)
                            session.commit()
                            
                            # Обновляем список заданий
                            tasks = session.query(Task).filter_by(quest_id=quest_id).order_by(Task.order).all()
                            quest = session.query(Quest).filter(Quest.id == quest_id).first()
                            
                            task_list = []
                            for t in tasks:
                                completed = session.query(Submission).filter_by(
                                    task_id=t.id, is_approved=True
                                ).first() is not None
                                task_list.append({
                                    'id': t.id,
                                    'title': t.title,
                                    'completed': completed
                                })
                            
                            await safe_edit_message(
                                callback.message,
                                f"✅ Задание и все его фото удалены!\n\nКвест: {quest.title}",
                                nav.task_management_menu(task_list, quest_id)
                            )
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[3]}")
            
            # Возврат к заданиям
            elif len(parts) == 4 and parts[0] == "back" and parts[1] == "to" and parts[2] == "tasks":
                try:
                    task_id = int(parts[3])
                    task = await get_task_by_id(task_id)
                    if task:
                        quest_id = task.quest_id
                        session = Session()
                        try:
                            tasks = session.query(Task).filter_by(quest_id=quest_id).order_by(Task.order).all()
                            quest = session.query(Quest).filter(Quest.id == quest_id).first()
                            
                            task_list = []
                            for t in tasks:
                                completed = session.query(Submission).filter_by(
                                    task_id=t.id, is_approved=True
                                ).first() is not None
                                task_list.append({
                                    'id': t.id,
                                    'title': t.title,
                                    'completed': completed
                                })
                            
                            await safe_edit_message(
                                callback.message,
                                f"📋 <b>Задания квеста '{quest.title}'</b>",
                                nav.task_management_menu(task_list, quest_id)
                            )
                        finally:
                            session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[3]}")
            
            # Добавление задания
            elif len(parts) == 3 and parts[0] == "add" and parts[1] == "task":
                try:
                    quest_id = int(parts[2])
                    await state.update_data(quest_id=quest_id)
                    await safe_edit_message(
                        callback.message,
                        "📝 Введите название нового задания:",
                        nav.cancel_button()
                    )
                    await state.set_state(TaskCreation.title)
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")
            
            # Создание квеста
            elif data == "create_quest":
                await safe_edit_message(
                    callback.message,
                    "📝 Введите название нового квеста:",
                    nav.cancel_button()
                )
                await state.set_state(QuestCreation.title)
            
            # Подтверждение отчета
            elif len(parts) == 2 and parts[0] == "approve":
                try:
                    sub_id = int(parts[1])
                    session = Session()
                    try:
                        sub = session.query(Submission).filter(Submission.id == sub_id).first()
                        if sub:
                            sub.is_approved = True
                            sub.approved_at = datetime.now()
                            session.commit()
                            
                            completed = session.query(Submission).filter_by(
                                user_id=sub.user_id, is_approved=True
                            ).count()
                            
                            quest = sub.task.quest
                            
                            # Проверяем завершение квеста
                            if completed >= quest.required_completions:
                                # Проверяем, не был ли уже завершен
                                existing = session.query(QuestCompletion).filter_by(
                                    quest_id=quest.id, user_id=sub.user_id
                                ).first()
                                
                                if not existing:
                                    comp = QuestCompletion(quest_id=quest.id, user_id=sub.user_id)
                                    session.add(comp)
                                    session.commit()
                                    
                                    # Отправляем поздравление
                                    await bot.send_message(
                                        GIRLFRIEND_ID,
                                        f"🎉 <b>ПОЗДРАВЛЯЮ!</b>\n\n"
                                        f"Ты выполнила квест <b>'{quest.title}'</b>!\n"
                                        f"🎁 Награда: {quest.reward}\n\n"
                                        f"Хочешь продолжить? Проверь новые квесты!",
                                        parse_mode=ParseMode.HTML
                                    )
                                    
                                    # Показываем следующий квест
                                    fake_message = types.Message(
                                        message_id=0,
                                        date=datetime.now(),
                                        chat=types.Chat(id=GIRLFRIEND_ID, type="private"),
                                        from_user=types.User(id=GIRLFRIEND_ID, is_bot=False, first_name="")
                                    )
                                    await show_current_quest(fake_message)
                            
                            await bot.send_message(
                                GIRLFRIEND_ID,
                                f"✅ Задание <b>'{sub.task.title}'</b> подтверждено!\n"
                                f"📊 Прогресс: {completed}/{quest.required_completions}",
                                parse_mode=ParseMode.HTML
                            )
                            
                            await safe_edit_message(
                                callback.message,
                                f"✅ Задание подтверждено!",
                                None
                            )
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[1]}")
            
            # Отклонение отчета
            elif len(parts) == 2 and parts[0] == "reject":
                try:
                    sub_id = int(parts[1])
                    session = Session()
                    try:
                        sub = session.query(Submission).filter(Submission.id == sub_id).first()
                        if sub:
                            task_title = sub.task.title
                            
                            # Удаляем фото перед удалением отчета
                            if sub.photo_url and os.path.exists(sub.photo_url):
                                try:
                                    os.remove(sub.photo_url)
                                    logger.info(f"Удалено фото отклоненного отчета: {sub.photo_url}")
                                except:
                                    pass
                            
                            session.delete(sub)
                            session.commit()
                            
                            await bot.send_message(
                                GIRLFRIEND_ID,
                                f"❌ Задание <b>'{task_title}'</b> отклонено.\n"
                                f"Попробуй выполнить его ещё раз!",
                                parse_mode=ParseMode.HTML
                            )
                            await safe_edit_message(callback.message, "❌ Задание отклонено", None)
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[1]}")
            
            # Возврат к действиям с квестом
            elif len(parts) == 3 and parts[0] == "quest" and parts[1] == "actions":
                try:
                    quest_id = int(parts[2])
                    quest = await get_quest_by_id(quest_id)
                    if quest:
                        await safe_edit_message(
                            callback.message,
                            f"📌 <b>{quest.title}</b>\n\nВыберите действие:",
                            nav.quest_actions_menu(quest_id)
                        )
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[2]}")

        # ПАНЕЛЬ ДЕВУШКИ
        elif user_id == GIRLFRIEND_ID:
            
            # Текущий квест
            if data == "current_quest":
                await show_current_quest(callback.message)
            
            # Моя статистика
            elif data == "my_stats":
                await show_my_stats(callback.message)
            
            # Достижения
            elif data == "achievements":
                await show_achievements(callback.message)
            
            # Начало выполнения задания
            elif len(parts) == 2 and parts[0] == "do":
                try:
                    task_id = int(parts[1])
                    
                    session = Session()
                    try:
                        task = session.query(Task).filter(Task.id == task_id).first()
                        
                        # Проверяем, нет ли уже неподтвержденного отчета
                        user = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
                        existing = session.query(Submission).filter_by(
                            task_id=task_id,
                            user_id=user.id,
                            is_approved=False
                        ).first()
                        
                        if existing:
                            await safe_edit_message(
                                callback.message,
                                "⏳ У вас уже есть неподтвержденный отчет по этому заданию!",
                                nav.back_button("current_quest")
                            )
                            return
                        
                        text = f"""
📌 <b>{task.title}</b>

{task.description}

💰 <b>Награда:</b> {task.points} очков

📸 Отправьте фото выполнения задания.
"""
                        await state.update_data(task_id=task_id)
                        await safe_edit_message(callback.message, text, nav.cancel_button())
                        await state.set_state(SubmissionStates.waiting_for_photo)
                    finally:
                        session.close()
                except ValueError:
                    logger.error(f"Ошибка преобразования ID: {parts[1]}")
    
    except Exception as e:
        logger.error(f"Ошибка: {e}")
        try:
            await callback.message.answer("❌ Произошла ошибка. Попробуйте снова.")
        except:
            pass

# Функция показа текущего квеста
async def show_current_quest(message: types.Message):
    """Показать текущий квест для девушки"""
    session = Session()
    try:
        # Ищем активный квест, который еще не завершен
        user = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
        completed_quest_ids = [cq.quest_id for cq in session.query(QuestCompletion).filter_by(user_id=user.id).all()]
        
        if completed_quest_ids:
            quest = session.query(Quest).filter(
                Quest.is_active == True,
                ~Quest.id.in_(completed_quest_ids)
            ).first()
        else:
            quest = session.query(Quest).filter_by(is_active=True).first()
        
        if not quest:
            await safe_edit_message(
                message,
                "🎉 <b>Поздравляю! Ты выполнила все квесты!</b>\n\nЖди новых заданий! 😊",
                nav.girlfriend_main_menu()
            )
            return
        
        tasks = session.query(Task).filter_by(quest_id=quest.id).order_by(Task.order).all()
        
        completed_ids = [s.task_id for s in session.query(Submission).filter_by(
            user_id=user.id, is_approved=True
        ).all()]
        
        pending_ids = [s.task_id for s in session.query(Submission).filter_by(
            user_id=user.id, is_approved=False
        ).all()]
        
        completed_count = len(completed_ids)
        today = date.today().isoformat()
        
        # Прогресс бар
        percent = int((completed_count / quest.required_completions) * 100) if quest.required_completions > 0 else 0
        bar = "█" * (percent // 10) + "░" * (10 - (percent // 10))
        
        text = f"""
🎯 <b>{quest.title}</b>

{quest.description}

<b>Прогресс:</b> {bar} {percent}%
<b>Выполнено:</b> {completed_count}/{quest.required_completions}
<b>Награда:</b> 🎁 {quest.reward}

<b>Задания:</b>
"""
        
        builder = InlineKeyboardBuilder()
        
        for t in tasks:
            if t.id in completed_ids:
                text += f"\n✅ <b>{t.title}</b> - {t.points} ⭐"
            elif t.id in pending_ids:
                text += f"\n⏳ <b>{t.title}</b> - {t.points} ⭐ (на проверке)"
            elif t.scheduled_date and t.scheduled_date > today:
                text += f"\n📅 <b>{t.title}</b> - {t.points} ⭐ (с {t.scheduled_date})"
            else:
                text += f"\n⬜ <b>{t.title}</b> - {t.points} ⭐"
                builder.button(text=f"📋 {t.title[:15]}", callback_data=f"do_{t.id}")
        
        builder.button(text="🔄 Обновить", callback_data="current_quest")
        builder.button(text="🏠 В меню", callback_data="main_menu")
        builder.adjust(1)
        
        await safe_edit_message(message, text, builder.as_markup())
    finally:
        session.close()

# Функция показа статистики
async def show_my_stats(message: types.Message):
    """Показать статистику девушки"""
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
        quests = session.query(Quest).filter_by(is_active=True).all()
        
        # Общая статистика
        total_completed = session.query(Submission).filter_by(
            user_id=user.id, is_approved=True
        ).count()
        
        total_pending = session.query(Submission).filter_by(
            user_id=user.id, is_approved=False
        ).count()
        
        total_points = 0
        submissions = session.query(Submission).filter_by(user_id=user.id, is_approved=True).all()
        for s in submissions:
            total_points += s.task.points
        
        # Статистика по дням
        last_7_days = []
        today = date.today()
        for i in range(7):
            day = today - timedelta(days=i)
            day_start = datetime(day.year, day.month, day.day)
            day_end = day_start + timedelta(days=1)
            count = session.query(Submission).filter(
                Submission.user_id == user.id,
                Submission.is_approved == True,
                Submission.approved_at >= day_start,
                Submission.approved_at < day_end
            ).count()
            last_7_days.append((day.strftime("%d.%m"), count))
        
        text = f"""
📊 <b>ТВОЯ СТАТИСТИКА</b> (обновлено {datetime.now().strftime('%H:%M:%S')})

👤 <b>Всего выполнено:</b> {total_completed} заданий
⭐ <b>Всего очков:</b> {total_points}
⏳ <b>На проверке:</b> {total_pending}

📅 <b>Активность за 7 дней:</b>
"""
        for day, count in reversed(last_7_days):
            bar = "█" * count + "░" * (5 - count)
            text += f"\n{day}: {bar} {count} зад."
        
        text += "\n\n<b>Прогресс по квестам:</b>\n"
        
        for quest in quests:
            completed = session.query(Submission).join(Task).filter(
                Task.quest_id == quest.id,
                Submission.user_id == user.id,
                Submission.is_approved == True
            ).count()
            
            done = session.query(QuestCompletion).filter_by(quest_id=quest.id, user_id=user.id).first()
            
            if done:
                text += f"\n✅ {quest.title} - ЗАВЕРШЁН! 🎁 {quest.reward}"
            else:
                bar = format_progress_bar(completed, quest.required_completions)
                text += f"\n📌 {quest.title}: {bar} {completed}/{quest.required_completions}"
        
        # Кнопка обновления
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data="my_stats")
        builder.button(text="◀️ Назад", callback_data="main_menu")
        builder.adjust(1)
        
        await safe_edit_message(message, text, builder.as_markup())
    finally:
        session.close()

# Функция показа достижений
async def show_achievements(message: types.Message):
    """Показать достижения девушки"""
    session = Session()
    try:
        user = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
        
        # Считаем достижения
        total_completed = session.query(Submission).filter_by(
            user_id=user.id, is_approved=True
        ).count()
        
        completed_quests = session.query(QuestCompletion).filter_by(user_id=user.id).count()
        
        # Разные достижения
        achievements = [
            ("🏆 Новичок", "Выполнить 1 задание", total_completed >= 1),
            ("⭐ Опытный", "Выполнить 10 заданий", total_completed >= 10),
            ("💪 Профи", "Выполнить 25 заданий", total_completed >= 25),
            ("👑 Легенда", "Выполнить 50 заданий", total_completed >= 50),
            ("🎯 Первый квест", "Завершить 1 квест", completed_quests >= 1),
            ("🌟 Мастер квестов", "Завершить 3 квеста", completed_quests >= 3),
        ]
        
        text = "🏆 <b>ТВОИ ДОСТИЖЕНИЯ</b>\n\n"
        
        for title, desc, earned in achievements:
            if earned:
                text += f"✅ <b>{title}</b> - {desc}\n"
            else:
                text += f"⬜ <b>{title}</b> - {desc}\n"
        
        builder = InlineKeyboardBuilder()
        builder.button(text="🔄 Обновить", callback_data="achievements")
        builder.button(text="◀️ Назад", callback_data="main_menu")
        builder.adjust(1)
        
        await safe_edit_message(message, text, builder.as_markup())
    finally:
        session.close()

# Обработка фото от девушки
@dp.message(F.from_user.id == GIRLFRIEND_ID, F.photo, SubmissionStates.waiting_for_photo)
async def handle_photo(message: types.Message, state: FSMContext):
    """Обработка фото для отчета"""
    data = await state.get_data()
    task_id = data.get('task_id')
    
    if not task_id:
        await state.clear()
        return
    
    # Показываем сообщение о загрузке
    loading_msg = await message.answer("⏳ Загружаю фото...")
    
    # Сохраняем фото
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    os.makedirs("photos", exist_ok=True)
    dest = f"photos/submission_{uuid.uuid4()}.jpg"
    
    # Скачиваем фото с повторными попытками
    success = await download_photo_with_retry(file, dest)
    
    if not success:
        await loading_msg.delete()
        await message.answer(
            "❌ Не удалось загрузить фото. Попробуйте еще раз или отправьте фото меньшего размера.",
            reply_markup=nav.cancel_button()
        )
        return
    
    await loading_msg.delete()
    await state.update_data(photo_path=dest)
    await safe_delete_message(message)
    
    # Если есть комментарий в подписи к фото
    if message.caption:
        # Отправляем отчет сразу
        await process_complete_submission(message, state, dest, message.caption)
    else:
        # Ждем комментарий
        await message.answer(
            "📝 Отправьте комментарий к фото:",
            reply_markup=nav.cancel_button()
        )
        await state.set_state(SubmissionStates.waiting_for_comment)

# Обработка комментария
@dp.message(F.from_user.id == GIRLFRIEND_ID, F.text, SubmissionStates.waiting_for_comment)
async def handle_comment(message: types.Message, state: FSMContext):
    """Обработка комментария для отчета"""
    data = await state.get_data()
    task_id = data.get('task_id')
    photo_path = data.get('photo_path')
    
    if not task_id or not photo_path:
        await state.clear()
        return
    
    await process_complete_submission(message, state, photo_path, message.text)

# Обработка случайного текста
@dp.message(F.from_user.id == GIRLFRIEND_ID, F.text, SubmissionStates.waiting_for_photo)
async def handle_unexpected_text(message: types.Message, state: FSMContext):
    """Если отправили текст вместо фото"""
    await safe_delete_message(message)
    await message.answer(
        "❌ Сначала отправьте фото выполнения задания!",
        reply_markup=nav.cancel_button()
    )

# Обработка случайного фото без комментария после комментария
@dp.message(F.from_user.id == GIRLFRIEND_ID, F.photo, SubmissionStates.waiting_for_comment)
async def handle_unexpected_photo(message: types.Message, state: FSMContext):
    """Если отправили еще одно фото вместо комментария"""
    await safe_delete_message(message)
    await message.answer(
        "❌ Сначала отправьте комментарий к предыдущему фото!",
        reply_markup=nav.cancel_button()
    )

# Функция отправки готового отчета
async def process_complete_submission(message: types.Message, state: FSMContext, photo_path: str, comment: str):
    """Обработка готового отчета (фото + комментарий)"""
    data = await state.get_data()
    task_id = data.get('task_id')
    
    session = Session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        user = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
        
        # Удаляем старые неподтвержденные отчеты и их фото
        old_subs = session.query(Submission).filter_by(
            task_id=task_id,
            user_id=user.id,
            is_approved=False
        ).all()
        for sub in old_subs:
            if sub.photo_url and os.path.exists(sub.photo_url):
                try:
                    os.remove(sub.photo_url)
                    logger.info(f"Удалено старое фото отчета: {sub.photo_url}")
                except:
                    pass
            session.delete(sub)
        
        # Создаем новый отчет
        sub = Submission(
            task_id=task_id,
            user_id=user.id,
            photo_url=photo_path,
            comment=comment,
            submitted_at=datetime.now()
        )
        session.add(sub)
        session.commit()
        
        # Отправляем подтверждение девушке
        await safe_delete_message(message)
        await message.answer("✅ <b>Отчет отправлен!</b>\nОжидайте подтверждения.", reply_markup=nav.girlfriend_main_menu())
        
        # Отправляем админу
        await bot.send_photo(
            ADMIN_ID,
            FSInputFile(photo_path),
            caption=f"📬 <b>Новый отчет!</b>\n\n"
                    f"📌 Задание: {task.title}\n"
                    f"💬 Комментарий: {comment}",
            reply_markup=nav.approve_reject_buttons(sub.id)
        )
        
    except Exception as e:
        logger.error(f"Ошибка при отправке отчета: {e}")
        await message.answer("❌ Ошибка при отправке отчета")
        # Удаляем временное фото
        if os.path.exists(photo_path):
            try:
                os.remove(photo_path)
            except:
                pass
    finally:
        session.close()
        await state.clear()

# Создание квеста
@dp.message(QuestCreation.title)
async def quest_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await safe_delete_message(message)
    await message.answer("📝 Введите описание квеста:", reply_markup=nav.cancel_button())
    await state.set_state(QuestCreation.description)

@dp.message(QuestCreation.description)
async def quest_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await safe_delete_message(message)
    await message.answer("🖼 Отправьте картинку или отправьте 'нет':", reply_markup=nav.cancel_button())
    await state.set_state(QuestCreation.image)

@dp.message(QuestCreation.image)
async def quest_image(message: types.Message, state: FSMContext):
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        os.makedirs("photos", exist_ok=True)
        dest = f"photos/quest_{uuid.uuid4()}.jpg"
        
        success = await download_photo_with_retry(file, dest)
        if success:
            optimize_image(dest)
            await state.update_data(image=dest)
        else:
            await state.update_data(image=None)
            await message.answer("⚠️ Не удалось загрузить фото, но квест будет создан без картинки.")
    else:
        await state.update_data(image=None)
    
    await safe_delete_message(message)
    await message.answer("🎁 Введите награду за квест:", reply_markup=nav.cancel_button())
    await state.set_state(QuestCreation.reward)

@dp.message(QuestCreation.reward)
async def quest_reward(message: types.Message, state: FSMContext):
    await state.update_data(reward=message.text)
    await safe_delete_message(message)
    await message.answer("🔢 Сколько заданий нужно выполнить для награды?", reply_markup=nav.cancel_button())
    await state.set_state(QuestCreation.required)

@dp.message(QuestCreation.required)
async def quest_required(message: types.Message, state: FSMContext):
    try:
        required = int(message.text)
        data = await state.get_data()
        
        session = Session()
        try:
            user = session.query(User).filter_by(telegram_id=message.from_user.id).first()
            
            quest = Quest(
                title=data['title'],
                description=data['description'],
                image_url=data.get('image'),
                reward=data['reward'],
                required_completions=required,
                created_by=user.id
            )
            session.add(quest)
            session.commit()
        finally:
            session.close()
        
        await safe_delete_message(message)
        await message.answer(
            "✅ <b>Квест успешно создан!</b>\n\nТеперь добавьте в него задания.",
            reply_markup=nav.admin_main_menu()
        )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите число!")

# Создание задания
@dp.message(TaskCreation.title)
async def task_title(message: types.Message, state: FSMContext):
    await state.update_data(title=message.text)
    await safe_delete_message(message)
    await message.answer("📝 Введите описание задания:", reply_markup=nav.cancel_button())
    await state.set_state(TaskCreation.description)

@dp.message(TaskCreation.description)
async def task_description(message: types.Message, state: FSMContext):
    await state.update_data(description=message.text)
    await safe_delete_message(message)
    await message.answer("🖼 Отправьте картинку или 'нет':", reply_markup=nav.cancel_button())
    await state.set_state(TaskCreation.image)

@dp.message(TaskCreation.image)
async def task_image(message: types.Message, state: FSMContext):
    if message.photo:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        os.makedirs("photos", exist_ok=True)
        dest = f"photos/task_{uuid.uuid4()}.jpg"
        
        success = await download_photo_with_retry(file, dest)
        if success:
            optimize_image(dest)
            await state.update_data(image=dest)
        else:
            await state.update_data(image=None)
            await message.answer("⚠️ Не удалось загрузить фото, но задание будет создано без картинки.")
    else:
        await state.update_data(image=None)
    
    await safe_delete_message(message)
    await message.answer("💰 Сколько очков даёт задание?", reply_markup=nav.cancel_button())
    await state.set_state(TaskCreation.points)

@dp.message(TaskCreation.points)
async def task_points(message: types.Message, state: FSMContext):
    try:
        points = int(message.text)
        await state.update_data(points=points)
        await safe_delete_message(message)
        await message.answer("📅 Введите дату (ГГГГ-ММ-ДД) или 'нет':", reply_markup=nav.cancel_button())
        await state.set_state(TaskCreation.date)
    except ValueError:
        await message.answer("❌ Введите число!")

@dp.message(TaskCreation.date)
async def task_date(message: types.Message, state: FSMContext):
    scheduled_date = None
    if message.text.lower() != 'нет':
        if not validate_date(message.text):
            await message.answer("❌ Неверный формат. Используйте ГГГГ-ММ-ДД")
            return
        scheduled_date = message.text
    
    data = await state.get_data()
    await safe_delete_message(message)
    
    session = Session()
    try:
        task_count = session.query(Task).filter_by(quest_id=data['quest_id']).count()
        task = Task(
            quest_id=data['quest_id'],
            title=data['title'],
            description=data['description'],
            image_url=data.get('image'),
            points=data['points'],
            scheduled_date=scheduled_date,
            order=task_count + 1
        )
        session.add(task)
        session.commit()
    finally:
        session.close()
    
    await message.answer("✅ <b>Задание добавлено!</b>", reply_markup=nav.admin_main_menu())
    await state.clear()

# Редактирование задания
@dp.message(TaskEdit.field)
async def edit_task_field(message: types.Message, state: FSMContext):
    data = await state.get_data()
    task_id = data.get('task_id')
    field = data.get('field')
    
    session = Session()
    try:
        task = session.query(Task).filter(Task.id == task_id).first()
        
        if task:
            if field == "title":
                task.title = message.text
            elif field == "description":
                task.description = message.text
            elif field == "points":
                try:
                    task.points = int(message.text)
                except ValueError:
                    await message.answer("❌ Введите число!")
                    return
            elif field == "date":
                if message.text.lower() == 'нет':
                    task.scheduled_date = None
                elif validate_date(message.text):
                    task.scheduled_date = message.text
                else:
                    await message.answer("❌ Неверный формат даты!")
                    return
            
            session.commit()
            
            await safe_delete_message(message)
            await message.answer("✅ <b>Задание обновлено!</b>", reply_markup=nav.admin_main_menu())
    finally:
        session.close()
    
    await state.clear()

# Запуск бота
async def main():
    # Создаем папку для фото
    os.makedirs("photos", exist_ok=True)
    
    # Очищаем временные фото при запуске (старше 1 дня)
    try:
        now = datetime.now()
        for filename in os.listdir("photos"):
            if filename.startswith("temp_"):
                filepath = os.path.join("photos", filename)
                file_time = datetime.fromtimestamp(os.path.getctime(filepath))
                if (now - file_time).days > 0:
                    os.remove(filepath)
                    logger.info(f"Удалено старое временное фото: {filename}")
    except Exception as e:
        logger.error(f"Ошибка при очистке временных фото: {e}")
    
    # Проверяем базу данных
    session = Session()
    try:
        admin = session.query(User).filter_by(telegram_id=ADMIN_ID).first()
        if not admin:
            admin = User(telegram_id=ADMIN_ID, is_admin=True)
            session.add(admin)
        
        girlfriend = session.query(User).filter_by(telegram_id=GIRLFRIEND_ID).first()
        if not girlfriend and GIRLFRIEND_ID != 0:
            girlfriend = User(telegram_id=GIRLFRIEND_ID, is_admin=False)
            session.add(girlfriend)
        
        session.commit()
    except Exception as e:
        logger.error(f"Ошибка при инициализации БД: {e}")
    finally:
        session.close()
    
    logger.info("🚀 Бот запущен!")
    logger.info(f"👤 Admin ID: {ADMIN_ID}")
    logger.info(f"👧 Girlfriend ID: {GIRLFRIEND_ID}")
    
    try:
        await dp.start_polling(bot)
    except (KeyboardInterrupt, SystemExit):
        logger.info("👋 Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())