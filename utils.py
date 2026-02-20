import os
from PIL import Image
from datetime import datetime

def optimize_image(filepath: str, max_size=(800, 800)):
    """Оптимизация изображения"""
    try:
        img = Image.open(filepath)
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        img.save(filepath, optimize=True, quality=85)
        return True
    except Exception as e:
        print(f"Ошибка оптимизации: {e}")
        return False

def format_progress_bar(completed: int, total: int, length: int = 10) -> str:
    """Форматирование прогресс-бара"""
    if total == 0:
        return "░" * length
    percent = int((completed / total) * 100)
    filled = percent // 10
    return "█" * filled + "░" * (length - filled)

def validate_date(date_str: str) -> bool:
    """Проверка формата даты"""
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
        return True
    except:
        return False

def cleanup_quest_files(quest_id: int):
    """Заглушка для совместимости"""
    pass