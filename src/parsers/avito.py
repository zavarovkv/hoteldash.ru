"""Парсер Авито (avito.ru) — best-effort, может требовать residential proxy."""

from __future__ import annotations

import logging
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class AvitoParser(BaseParser):
    source_name = "avito"

    async def _detect_block(self, page: Page) -> Optional[str]:
        """Проверка на Cloudflare и блокировку Авито."""
        base_result = await super()._detect_block(page)
        if base_result:
            return base_result

        cloudflare_selectors = [
            "#challenge-running",
            "#challenge-stage",
            "[class*='cf-browser-verification']",
            "iframe[src*='challenges.cloudflare']",
        ]
        for selector in cloudflare_selectors:
            if await page.query_selector(selector):
                return f"cloudflare challenge ({selector})"

        try:
            title = await page.title()
            if "just a moment" in title.lower() or "cloudflare" in title.lower():
                return "cloudflare title detected"
        except Exception:
            pass

        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        # Авито — объявления без привязки к датам, ищем цену из карточки
        await page.wait_for_timeout(3000)

        selectors = [
            "[data-marker='item-view/item-price']",
            "[itemprop='price']",
            "[class*='price-value']",
            "[class*='item-price']",
            "[class*='ItemPrice']",
            "[class*='price-text']",
            "span[class*='price']",
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                # itemprop='price' может быть в атрибуте content
                content = await element.get_attribute("content")
                if content:
                    price = self.parse_price_text(content)
                    if price is not None:
                        return ParseResult(price=price, raw_text=content, error=None)

                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Последняя попытка — ищем по meta-тегу
        try:
            meta = await page.query_selector("meta[itemprop='price']")
            if meta:
                content = await meta.get_attribute("content")
                if content:
                    price = self.parse_price_text(content)
                    if price is not None:
                        return ParseResult(price=price, raw_text=content, error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
