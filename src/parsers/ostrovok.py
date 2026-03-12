"""Парсер Островок (ostrovok.ru)."""

from __future__ import annotations

import json
import logging
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class OstrovokParser(BaseParser):
    source_name = "ostrovok"

    async def _extract_price(self, page: Page) -> ParseResult:
        # Попробуем найти цену в ld+json
        ld_json_result = await self._try_ld_json(page)
        if ld_json_result and ld_json_result.price is not None:
            return ld_json_result

        # Ищем цену через CSS-селекторы
        selectors = [
            "[data-testid='price']",
            "[class*='price-amount']",
            "[class*='PriceAmount']",
            "[class*='hotel-price']",
            ".min-price",
            "[class*='room-price'] [class*='amount']",
            "[class*='RoomPrice'] [class*='Amount']",
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Ищем по тексту ₽
        try:
            rub_elements = await page.query_selector_all("[class*='price'], [class*='Price'], [class*='rate'], [class*='Rate']")
            for el in rub_elements[:10]:
                text = await el.inner_text()
                if "₽" in text or "руб" in text.lower():
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text.strip(), error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")

    async def _try_ld_json(self, page: Page) -> Optional[ParseResult]:
        """Пытается извлечь цену из JSON-LD разметки."""
        try:
            scripts = await page.query_selector_all('script[type="application/ld+json"]')
            for script in scripts:
                text = await script.inner_text()
                data = json.loads(text)
                offers = data.get("offers") or data.get("priceRange")
                if isinstance(offers, dict):
                    price_str = str(offers.get("price", ""))
                    if price_str:
                        price = self.parse_price_text(price_str)
                        if price is not None:
                            return ParseResult(price=price, raw_text=price_str, error=None)
                elif isinstance(offers, list):
                    for offer in offers:
                        price_str = str(offer.get("price", ""))
                        if price_str:
                            price = self.parse_price_text(price_str)
                            if price is not None:
                                return ParseResult(price=price, raw_text=price_str, error=None)
        except Exception:
            pass
        return None
