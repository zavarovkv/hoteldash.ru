"""Парсер Otello (otello.ru) — перехват API + DOM-фоллбэк."""

from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page, Response

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

_API_WAIT_MAX_MS = 30_000
_API_POLL_INTERVAL_MS = 500


class OtelloParser(BaseParser):
    source_name = "otello"
    needs_browser = True

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы с ценами, фоллбэк на DOM."""
        captured_prices: list[int] = []

        async def on_response(response: Response):
            try:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or "json" not in content_type:
                    return

                body = await response.json()
                prices = self._extract_prices_from_api(body)
                if prices:
                    logger.info(
                        "[%s] API %s → %d цен",
                        self.source_name, response.url[:80], len(prices),
                    )
                    captured_prices.extend(prices)
            except Exception:
                pass

        page.on("response", on_response)

        logger.info(
            "[%s] %s | checkin=%s",
            self.source_name, hotel_slug, checkin_date,
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[%s] goto timeout: %s", self.source_name, type(e).__name__)

        # Ждём рендеринг SPA
        await page.wait_for_timeout(5000)

        # Поллинг — ждём API-ответ с ценами
        waited = 0
        while not captured_prices and waited < _API_WAIT_MAX_MS:
            await page.wait_for_timeout(_API_POLL_INTERVAL_MS)
            waited += _API_POLL_INTERVAL_MS

        if captured_prices:
            min_price = min(captured_prices)
            logger.info(
                "[%s] %s | %s | мин. цена (API): %d руб. (из %d вариантов)",
                self.source_name, hotel_slug, checkin_date,
                min_price, len(captured_prices),
            )
            return ParseResult(price=min_price, raw_text=f"{min_price} ₽", error=None)

        # Фоллбэк: парсинг цен из DOM
        logger.info("[%s] API цен нет, пробуем DOM", self.source_name)
        return await self._extract_price(page)

    def _extract_prices_from_api(self, data, depth: int = 0) -> list[int]:
        """Рекурсивно ищет цены в JSON-ответе API."""
        prices = []
        if depth > 10 or len(prices) > 200:
            return prices

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                if key_lower in (
                    "price", "total_price", "min_price", "amount",
                    "sell_price", "total", "rate", "cost",
                ):
                    p = self._parse_price_value(value)
                    if p is not None:
                        prices.append(p)

            for value in data.values():
                if isinstance(value, (dict, list)):
                    prices.extend(self._extract_prices_from_api(value, depth + 1))

        elif isinstance(data, list):
            for item in data:
                if isinstance(item, (dict, list)):
                    prices.extend(self._extract_prices_from_api(item, depth + 1))

        return prices

    @staticmethod
    def _parse_price_value(val) -> Optional[int]:
        """Конвертирует значение цены в целое число."""
        if val is None:
            return None
        try:
            price = int(float(val))
            if 500 <= price <= 1_000_000:
                return price
        except (ValueError, TypeError, OverflowError):
            pass
        if isinstance(val, str):
            cleaned = re.sub(r"[^\d]", "", val)
            if cleaned:
                try:
                    price = int(cleaned)
                    if 500 <= price <= 1_000_000:
                        return price
                except (ValueError, OverflowError):
                    pass
        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает минимальную цену из DOM."""
        # Ищем все текстовые элементы с символом ₽ или "руб"
        price_texts = await page.evaluate("""
            () => {
                const results = [];
                const walker = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT, null, false
                );
                while (walker.nextNode()) {
                    const text = walker.currentNode.textContent.trim();
                    if (text && (text.includes('₽') || text.includes('руб'))
                        && /\\d/.test(text) && text.length < 50) {
                        results.push(text);
                    }
                }
                return results;
            }
        """)

        prices = []
        for text in price_texts:
            cleaned = re.sub(r"[^\d]", "", text)
            if cleaned:
                try:
                    price = int(cleaned)
                    if 500 <= price <= 1_000_000:
                        prices.append(price)
                except (ValueError, OverflowError):
                    pass

        if prices:
            min_price = min(prices)
            logger.info(
                "[%s] DOM → мин. цена: %d руб. (из %d)",
                self.source_name, min_price, len(prices),
            )
            return ParseResult(price=min_price, raw_text=f"{min_price} ₽", error=None)

        return ParseResult(price=None, raw_text=None, error="no prices found")
