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
        # Ждём загрузку формы TravelLine
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(5000)

        # Ищем кнопку "Найти" во всех frames (TravelLine использует nested iframes)
        target_frame = None
        for frame in page.frames:
            try:
                btn = await frame.query_selector("button")
                if btn:
                    btn_text = await btn.inner_text()
                    logger.info("[%s] frame '%s' имеет кнопку: '%s'", self.source_name, frame.name[:30] if frame.name else "unnamed", btn_text.strip()[:50])
                    if "найти" in btn_text.lower() or "search" in btn_text.lower():
                        await btn.click()
                        logger.info("[%s] Кнопка 'Найти' нажата в frame '%s'", self.source_name, frame.name or frame.url[:60])
                        target_frame = frame
                        break
            except Exception:
                continue

        if not target_frame:
            logger.warning("[%s] Кнопка 'Найти' не найдена ни в одном frame", self.source_name)

        # Ждём загрузку результатов после поиска
        await page.wait_for_timeout(15000)

        # Скриншот для отладки
        await self._save_screenshot(page, "tl_debug", "after_search")

        # Ищем цены во всех frames
        for frame in page.frames:
            try:
                frame_text = await frame.evaluate("() => document.body ? document.body.innerText.substring(0, 500) : ''")
                if "₽" in frame_text or "руб" in frame_text.lower():
                    logger.info("[%s] Найден текст с ценами в frame '%s': %s", self.source_name, frame.name or "unnamed", frame_text[:200])
                    target_frame = frame
                    break
            except Exception:
                continue

        # Логируем текст из target_frame или main page
        body_text = ""
        if target_frame:
            try:
                body_text = await target_frame.evaluate("() => document.body ? document.body.innerText.substring(0, 1000) : ''")
            except Exception:
                pass
        if not body_text:
            body_text = await page.evaluate("() => document.body ? document.body.innerText.substring(0, 1000) : ''")
        logger.info("[%s] Текст на странице: %s", self.source_name, body_text[:300])

        # Ищем цены по CSS-селекторам во ВСЕХ frames
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

        for frame in page.frames:
            for selector in selectors:
                try:
                    elements = await frame.query_selector_all(selector)
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

        # Fallback: ищем паттерн цены в тексте всех frames
        for frame in page.frames:
            try:
                all_text = await frame.evaluate("() => document.body ? document.body.innerText : ''")
                matches = re.findall(r'([\d\s]+)\s*₽', all_text)
                if not matches:
                    matches = re.findall(r'([\d\s]+)\s*руб', all_text, re.IGNORECASE)
                for match in matches[:10]:
                    price = self.parse_price_text(match + '₽')
                    if price is not None:
                        return ParseResult(price=price, raw_text=match.strip() + ' ₽', error=None)
            except Exception:
                continue

        return ParseResult(price=None, raw_text=None, error="price element not found")
