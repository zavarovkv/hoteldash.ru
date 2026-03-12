"""Утилиты для обхода анти-бот защит."""

import asyncio
import logging
import random

from config.settings import (
    DELAY_BETWEEN_PAGES_MIN,
    DELAY_BETWEEN_PAGES_MAX,
    DELAY_BETWEEN_HOTELS_MIN,
    DELAY_BETWEEN_HOTELS_MAX,
)

logger = logging.getLogger(__name__)


async def delay_between_pages():
    """Случайная задержка между загрузками страниц."""
    delay = random.uniform(DELAY_BETWEEN_PAGES_MIN, DELAY_BETWEEN_PAGES_MAX)
    logger.debug("Задержка между страницами: %.1f сек", delay)
    await asyncio.sleep(delay)


async def delay_between_hotels():
    """Случайная задержка между отелями."""
    delay = random.uniform(DELAY_BETWEEN_HOTELS_MIN, DELAY_BETWEEN_HOTELS_MAX)
    logger.debug("Задержка между отелями: %.1f сек", delay)
    await asyncio.sleep(delay)


def shuffle_items(items: list) -> list:
    """Возвращает перемешанную копию списка."""
    shuffled = items.copy()
    random.shuffle(shuffled)
    return shuffled
