from aiogram.utils.keyboard import InlineKeyboardBuilder

def admin_main_menu():
    """Главное меню админа"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Статистика девушки", callback_data="girl_stats")
    builder.button(text="📋 Управление квестами", callback_data="manage_quests")
    builder.button(text="➕ Создать квест", callback_data="create_quest")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def girlfriend_main_menu():
    """Главное меню девушки"""
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Текущий квест", callback_data="current_quest")
    builder.button(text="📊 Моя статистика", callback_data="my_stats")
    builder.button(text="🏆 Достижения", callback_data="achievements")
    builder.button(text="🏠 Главное меню", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def back_button(callback_data: str = "main_menu"):
    """Кнопка возврата"""
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️ Назад", callback_data=callback_data)
    return builder.as_markup()

def cancel_button():
    """Кнопка отмены"""
    builder = InlineKeyboardBuilder()
    builder.button(text="❌ Отмена", callback_data="cancel_action")
    return builder.as_markup()

def quest_management_menu(quests: list):
    """Меню управления квестами с возможностью удаления"""
    builder = InlineKeyboardBuilder()
    for quest in quests:
        builder.button(text=f"📌 {quest['title']} ({quest['tasks']} заданий)", 
                      callback_data=f"manage_quest_{quest['id']}")
    builder.button(text="➕ Создать новый квест", callback_data="create_quest")
    builder.button(text="◀️ Назад", callback_data="main_menu")
    builder.adjust(1)
    return builder.as_markup()

def quest_actions_menu(quest_id: int):
    """Меню действий с квестом"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Управление заданиями", callback_data=f"manage_quest_tasks_{quest_id}")
    builder.button(text="❌ Удалить квест", callback_data=f"delete_quest_{quest_id}")
    builder.button(text="◀️ Назад", callback_data="manage_quests")
    builder.adjust(1)
    return builder.as_markup()

def task_management_menu(tasks: list, quest_id: int):
    """Меню управления заданиями"""
    builder = InlineKeyboardBuilder()
    for task in tasks:
        status = "✅" if task['completed'] else "📝"
        builder.button(text=f"{status} {task['title'][:15]}", 
                      callback_data=f"edit_task_{task['id']}")
    builder.button(text="➕ Добавить задание", callback_data=f"add_task_{quest_id}")
    builder.button(text="◀️ Назад", callback_data=f"quest_actions_{quest_id}")
    builder.adjust(1)
    return builder.as_markup()

def task_edit_menu(task_id: int):
    """Меню редактирования задания"""
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Название", callback_data=f"edit_title_{task_id}")
    builder.button(text="📄 Описание", callback_data=f"edit_desc_{task_id}")
    builder.button(text="💰 Очки", callback_data=f"edit_points_{task_id}")
    builder.button(text="📅 Дату", callback_data=f"edit_date_{task_id}")
    builder.button(text="❌ Удалить задание", callback_data=f"delete_task_{task_id}")
    builder.button(text="◀️ Назад", callback_data=f"back_to_tasks_{task_id}")
    builder.adjust(2, 2, 1, 1)
    return builder.as_markup()

def approve_reject_buttons(submission_id: int):
    """Кнопки подтверждения/отклонения отчета"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data=f"approve_{submission_id}")
    builder.button(text="❌ Отклонить", callback_data=f"reject_{submission_id}")
    builder.adjust(2)
    return builder.as_markup()

def confirm_delete_quest(quest_id: int):
    """Подтверждение удаления квеста"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_delete_quest_{quest_id}")
    builder.button(text="❌ Нет, отмена", callback_data=f"quest_actions_{quest_id}")
    builder.adjust(1)
    return builder.as_markup()

def confirm_delete_task(task_id: int):
    """Подтверждение удаления задания"""
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Да, удалить", callback_data=f"confirm_delete_task_{task_id}")
    builder.button(text="❌ Нет, отмена", callback_data=f"edit_task_{task_id}")
    builder.adjust(1)
    return builder.as_markup()