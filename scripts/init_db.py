"""Создание таблиц в БД."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.db import engine
from src.models import Base


def init_db():
    print("Создаю таблицы...")
    Base.metadata.create_all(engine)
    print("Таблицы созданы успешно!")


if __name__ == "__main__":
    init_db()
