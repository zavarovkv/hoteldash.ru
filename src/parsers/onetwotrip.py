"""Парсер OneTwoTrip (onetwotrip.com)."""

from __future__ import annotations

import logging
from typing import List

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class OneTwoTripParser(BaseParser):
    source_name = "onetwotrip"

    def __init__(self):
        self._api_prices: list[int] = []

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает fetch-ответы React SPA."""
        self._api_prices = []

        async def capture_response(response):
            try:
                if response.status == 200 and any(
                    pattern in response.url
                    for pattern in ["/api/", "hotels/search", "hotel/rates", "hotel/rooms"]
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
        """Рекурсивно ищет цены в JSON-ответе."""
        if depth > 10:
            return
        if isinstance(data, dict):
            for key in ("price", "totalPrice", "total", "amount", "min_price", "rate"):
                if key in data:
                    val = data[key]
                    if isinstance(val, (int, float)) and 100 < val < 10_000_000:
                        self._api_prices.append(int(val))
                    elif isinstance(val, dict):
                        for sub_key in ("value", "amount", "rub", "RUB"):
                            if sub_key in val:
                                v = val[sub_key]
                                if isinstance(v, (int, float)) and 100 < v < 10_000_000:
                                    self._api_prices.append(int(v))
            for v in data.values():
                self._extract_prices_from_api(v, depth + 1)
        elif isinstance(data, list):
            for item in data[:50]:
                self._extract_prices_from_api(item, depth + 1)

    async def _extract_price(self, page: Page) -> ParseResult:
        # Проверяем перехваченные API
        if self._api_prices:
            min_price = min(self._api_prices)
            return ParseResult(price=min_price, raw_text=str(min_price), error=None)

        # Ждём React SPA
        await page.wait_for_timeout(5000)

        selectors = [
            "[class*='price-value']",
            "[class*='PriceValue']",
            "[class*='room-price']",
            "[class*='RoomPrice']",
            "[data-testid='price']",
            "[class*='hotel-price']",
        ]

        for selector in selectors:
            element = await page.query_selector(selector)
            if element:
                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Последняя попытка — поиск по ₽
        try:
            elements = await page.query_selector_all("[class*='price'], [class*='Price']")
            for el in elements[:20]:
                text = await el.inner_text()
                if "₽" in text or "руб" in text.lower():
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text.strip(), error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
