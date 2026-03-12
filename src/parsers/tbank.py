"""Парсер Т-Банк Путешествия (tbank.ru/travel)."""

from __future__ import annotations

import json
import logging
from typing import List

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class TbankParser(BaseParser):
    source_name = "tbank"

    def __init__(self):
        self._api_prices: list[int] = []

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы React SPA перед загрузкой страницы."""
        self._api_prices = []

        async def capture_response(response):
            try:
                if response.status == 200 and any(
                    pattern in response.url
                    for pattern in ["/api/hotel", "/v1/hotel", "rates", "rooms", "prices"]
                ):
                    content_type = response.headers.get("content-type", "")
                    if "json" in content_type:
                        body = await response.json()
                        self._extract_prices_from_api(body)
            except Exception:
                pass

        page.on("response", capture_response)
        try:
            result = await super().scrape(page, url, hotel_slug, checkin_date)
        finally:
            page.remove_listener("response", capture_response)

        return result

    def _extract_prices_from_api(self, data, depth=0):
        """Рекурсивно ищет цены в JSON-ответе API."""
        if depth > 10:
            return
        if isinstance(data, dict):
            for key in ("price", "totalPrice", "total_price", "amount", "min_price", "minPrice"):
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and 100 < val < 10_000_000:
                        self._api_prices.append(int(val))
                    elif isinstance(val, dict) and "value" in val:
                        v = val["value"]
                        if isinstance(v, (int, float)) and 100 < v < 10_000_000:
                            self._api_prices.append(int(v))
            for v in data.values():
                self._extract_prices_from_api(v, depth + 1)
        elif isinstance(data, list):
            for item in data[:50]:
                self._extract_prices_from_api(item, depth + 1)

    async def _extract_price(self, page: Page) -> ParseResult:
        # Сначала проверяем перехваченные API-ответы
        if self._api_prices:
            min_price = min(self._api_prices)
            return ParseResult(price=min_price, raw_text=str(min_price), error=None)

        # Ждём рендеринга React SPA
        await page.wait_for_timeout(5000)

        selectors = [
            "[data-qa='hotel-price']",
            "[data-testid='price']",
            "[class*='Price_price']",
            "[class*='price_amount']",
            "[class*='RoomPrice']",
            "[class*='room-price']",
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Поиск по содержимому ₽
        try:
            elements = await page.query_selector_all("span, div, p")
            for el in elements[:100]:
                text = await el.inner_text()
                if "₽" in text and len(text) < 30:
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text.strip(), error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
