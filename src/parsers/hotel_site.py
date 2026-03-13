"""Парсер сайта отеля (TravelLine / Bnovo виджет)."""

from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: Optional[str] = None):
        self.widget = widget  # 'travelline', 'bnovo', etc.

    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает цену со страницы TravelLine booking engine."""
        # Ждём загрузку результатов (Angular SPA рендерит комнаты)
        # Пробуем дождаться появления элементов с ценами
        try:
            await page.wait_for_selector(
                "[class*='price'], [class*='room'], [class*='rate'], [class*='accommodation']",
                timeout=20000,
            )
        except Exception:
            pass
        await page.wait_for_timeout(5000)

        # Логируем что видим на странице
        body_text = await page.evaluate("() => document.body ? document.body.innerText.substring(0, 1000) : ''")
        logger.info("[%s] Текст на странице: %s", self.source_name, body_text[:300])

        # Ищем цены по CSS-селекторам TravelLine
        selectors = [
            "[class*='room-price']",
            "[class*='price-value']",
            "[class*='rate-price']",
            "[class*='total-price']",
            "[class*='p-price']",
            "[class*='cost']",
            "[class*='amount']",
            "[class*='price']",
        ]

        for selector in selectors:
            try:
                elements = await page.query_selector_all(selector)
                for el in elements[:10]:
                    raw_text = await el.inner_text()
                    raw_text = raw_text.strip()
                    if not raw_text:
                        continue
                    price = self.parse_price_text(raw_text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=raw_text, error=None)
            except Exception:
                continue

        # Fallback: ищем паттерн цены в тексте страницы
        try:
            all_text = await page.evaluate("() => document.body ? document.body.innerText : ''")
            # Ищем числа с ₽ или "руб"
            matches = re.findall(r'([\d\s]+)\s*₽', all_text)
            if not matches:
                matches = re.findall(r'([\d\s]+)\s*руб', all_text, re.IGNORECASE)
            for match in matches[:10]:
                price = self.parse_price_text(match + '₽')
                if price is not None:
                    return ParseResult(price=price, raw_text=match.strip() + ' ₽', error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
