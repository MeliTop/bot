from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime

# Создаем engine
engine = create_engine('sqlite:///quests.db', echo=False)

# Создаем Base
Base = declarative_base()

# Создаем sessionmaker
Session = sessionmaker(bind=engine)

# Модели
class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    telegram_id = Column(Integer, unique=True)
    username = Column(String)
    is_admin = Column(Boolean, default=False)
    quests = relationship("Quest", back_populates="creator")
    submissions = relationship("Submission", back_populates="user")

class Quest(Base):
    __tablename__ = 'quests'
    id = Column(Integer, primary_key=True)
    title = Column(String)
    description = Column(Text)
    image_url = Column(String)
    reward = Column(String)
    required_completions = Column(Integer)
    created_at = Column(DateTime, default=datetime.now)
    is_active = Column(Boolean, default=True)
    created_by = Column(Integer, ForeignKey('users.id'))
    creator = relationship("User", back_populates="quests")
    tasks = relationship("Task", back_populates="quest", cascade="all, delete-orphan")
    completions = relationship("QuestCompletion", back_populates="quest")

class Task(Base):
    __tablename__ = 'tasks'
    id = Column(Integer, primary_key=True)
    quest_id = Column(Integer, ForeignKey('quests.id'))
    title = Column(String)
    description = Column(Text)
    image_url = Column(String)
    points = Column(Integer, default=1)
    order = Column(Integer)
    scheduled_date = Column(String, nullable=True)
    is_completed = Column(Boolean, default=False)
    quest = relationship("Quest", back_populates="tasks")
    submissions = relationship("Submission", back_populates="task", cascade="all, delete-orphan")

class Submission(Base):
    __tablename__ = 'submissions'
    id = Column(Integer, primary_key=True)
    task_id = Column(Integer, ForeignKey('tasks.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    photo_url = Column(String)
    comment = Column(Text)
    submitted_at = Column(DateTime, default=datetime.now)
    is_approved = Column(Boolean, default=False)
    approved_at = Column(DateTime, nullable=True)
    task = relationship("Task", back_populates="submissions")
    user = relationship("User", back_populates="submissions")

class QuestCompletion(Base):
    __tablename__ = 'quest_completions'
    id = Column(Integer, primary_key=True)
    quest_id = Column(Integer, ForeignKey('quests.id'))
    user_id = Column(Integer, ForeignKey('users.id'))
    completed_at = Column(DateTime, default=datetime.now)
    reward_claimed = Column(Boolean, default=False)
    quest = relationship("Quest", back_populates="completions")

# Создаем таблицы
Base.metadata.create_all(engine)