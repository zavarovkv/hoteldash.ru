"""Парсер Яндекс Путешествия (travel.yandex.ru)."""

from __future__ import annotations

import logging
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class YandexTravelParser(BaseParser):
    source_name = "yandex_travel"

    async def _detect_block(self, page: Page) -> Optional[str]:
        """Расширенная проверка на SmartCaptcha Яндекса."""
        base_result = await super()._detect_block(page)
        if base_result:
            return base_result

        yandex_captcha_selectors = [
            ".CheckboxCaptcha",
            ".SmartCaptcha",
            "[class*='SmartCaptcha']",
            "iframe[src*='smartcaptcha']",
            "[class*='captcha-wrapper']",
        ]
        for selector in yandex_captcha_selectors:
            if await page.query_selector(selector):
                return f"yandex SmartCaptcha ({selector})"

        # Проверяем текст страницы на признаки блокировки
        try:
            body_text = await page.inner_text("body")
            block_phrases = ["нам нужно убедиться", "подтвердите, что вы не робот", "доступ ограничен"]
            for phrase in block_phrases:
                if phrase.lower() in body_text.lower():
                    return f"block phrase detected: {phrase}"
        except Exception:
            pass

        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        # Ждём загрузку SPA
        await page.wait_for_timeout(5000)

        selectors = [
            "[class*='OfferPrice']",
            "[class*='offer-price']",
            "[class*='HotelPrice']",
            "[class*='hotel-price']",
            "[data-testid='offer-price']",
            "[class*='PriceBlock']",
            "[class*='price-block']",
            "[class*='MinPrice']",
            "[class*='min-price']",
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            for element in elements[:5]:
                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Поиск по символу рубля
        try:
            all_elements = await page.query_selector_all("span, div")
            for el in all_elements[:150]:
                text = await el.inner_text()
                text = text.strip()
                if ("₽" in text or "руб" in text.lower()) and len(text) < 30:
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text, error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
