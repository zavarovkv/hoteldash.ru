"""Абстрактный базовый парсер."""

from __future__ import annotations

import logging
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from playwright.async_api import Page

from config.settings import (
    ELEMENT_WAIT_TIMEOUT,
    SCREENSHOTS_DIR,
    SAVE_SCREENSHOTS_ON_ERROR,
    MAX_RETRIES,
    RETRY_DELAY,
)

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    price: int | None
    raw_text: str | None
    error: str | None


class BaseParser(ABC):
    """Базовый класс для всех OTA-парсеров."""

    source_name: str = ""

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Загружает страницу и извлекает цену."""
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "[%s] %s | checkin=%s | попытка %d",
                    self.source_name, hotel_slug, checkin_date, attempt,
                )

                await page.goto(url, wait_until="domcontentloaded")
                await page.wait_for_timeout(3000)

                block_msg = await self._detect_block(page)
                if block_msg:
                    logger.warning("[%s] Обнаружена блокировка: %s", self.source_name, block_msg)
                    if attempt < MAX_RETRIES:
                        await page.wait_for_timeout(RETRY_DELAY * 1000)
                        continue
                    return ParseResult(price=None, raw_text=None, error=f"blocked: {block_msg}")

                result = await self._extract_price(page)

                if result.price is not None:
                    logger.info(
                        "[%s] %s | %s | цена: %d руб.",
                        self.source_name, hotel_slug, checkin_date, result.price,
                    )
                elif result.error:
                    logger.warning(
                        "[%s] %s | %s | ошибка: %s",
                        self.source_name, hotel_slug, checkin_date, result.error,
                    )

                return result

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "[%s] %s | %s | исключение (попытка %d): %s",
                    self.source_name, hotel_slug, checkin_date, attempt, error_msg,
                )

                if SAVE_SCREENSHOTS_ON_ERROR:
                    await self._save_screenshot(page, hotel_slug, checkin_date)

                if attempt < MAX_RETRIES:
                    await page.wait_for_timeout(RETRY_DELAY * 1000)
                    continue

                return ParseResult(price=None, raw_text=None, error=error_msg)

        return ParseResult(price=None, raw_text=None, error="max retries exceeded")

    @abstractmethod
    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает цену со страницы. Реализуется в каждом парсере."""
        ...

    async def _detect_block(self, page: Page) -> Optional[str]:
        """Проверяет наличие капчи или блокировки. Возвращает описание или None."""
        captcha_selectors = [
            ".captcha",
            "#captcha",
            "[class*='captcha']",
            ".CheckboxCaptcha",
            "iframe[src*='captcha']",
            "[class*='challenge']",
        ]
        for selector in captcha_selectors:
            if await page.query_selector(selector):
                return f"captcha detected ({selector})"
        return None

    @staticmethod
    def parse_price_text(text: Optional[str]) -> Optional[int]:
        """Парсит текст цены: '12 500 ₽' → 12500."""
        if not text:
            return None
        digits = re.sub(r"[^\d]", "", text)
        if not digits:
            return None
        value = int(digits)
        if value < 100 or value > 10_000_000:
            return None
        return value

    async def _save_screenshot(self, page: Page, hotel_slug: str, checkin_date: str):
        """Сохраняет скриншот страницы для диагностики."""
        try:
            os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{self.source_name}_{hotel_slug}_{checkin_date}_{timestamp}.png"
            path = os.path.join(SCREENSHOTS_DIR, filename)
            await page.screenshot(path=path, full_page=True)
            logger.info("Скриншот сохранён: %s", path)
        except Exception as e:
            logger.debug("Не удалось сохранить скриншот: %s", e)
