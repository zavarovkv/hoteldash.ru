"""Парсер Островок (ostrovok.ru) — перехват API-ответов через Playwright."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

from playwright.async_api import Page, Response

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class OstrovokParser(BaseParser):
    source_name = "ostrovok"
    needs_browser = True

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы с ценами вместо парсинга DOM."""
        captured_prices: list[int] = []
        captured_responses: list[dict] = []

        async def on_response(response: Response):
            try:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or "json" not in content_type:
                    return

                body = await response.json()
                prices = self._extract_prices_from_json(body)
                if prices:
                    logger.info(
                        "[%s] API %s → %d цен найдено",
                        self.source_name, response.url[:80], len(prices),
                    )
                    captured_prices.extend(prices)
                else:
                    captured_responses.append({
                        "url": response.url[:120],
                        "keys": list(body.keys()) if isinstance(body, dict) else type(body).__name__,
                    })
            except Exception:
                pass

        page.on("response", on_response)

        for attempt in range(1, 3):
            try:
                logger.info(
                    "[%s] %s | checkin=%s | попытка %d",
                    self.source_name, hotel_slug, checkin_date, attempt,
                )

                await page.goto(url, wait_until="domcontentloaded")
                # Ждём загрузки API-ответов с ценами
                await page.wait_for_timeout(10000)

                if captured_prices:
                    min_price = min(captured_prices)
                    logger.info(
                        "[%s] %s | %s | мин. цена: %d руб. (из %d вариантов)",
                        self.source_name, hotel_slug, checkin_date,
                        min_price, len(captured_prices),
                    )
                    return ParseResult(
                        price=min_price,
                        raw_text=f"{min_price} ₽",
                        error=None,
                    )

                # Логируем что пришло для диагностики
                if captured_responses:
                    logger.info(
                        "[%s] JSON-ответы без цен: %s",
                        self.source_name,
                        json.dumps(captured_responses[:5], ensure_ascii=False)[:500],
                    )

                if attempt < 2:
                    captured_prices.clear()
                    captured_responses.clear()
                    await page.wait_for_timeout(5000)
                    continue

                return ParseResult(price=None, raw_text=None, error="no prices in API responses")

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "[%s] %s | %s | ошибка (попытка %d): %s",
                    self.source_name, hotel_slug, checkin_date, attempt, error_msg,
                )
                if attempt < 2:
                    await page.wait_for_timeout(5000)
                    continue
                return ParseResult(price=None, raw_text=None, error=error_msg)

        return ParseResult(price=None, raw_text=None, error="max retries exceeded")

    def _extract_prices_from_json(self, data, depth: int = 0) -> list[int]:
        """Рекурсивно ищет цены в JSON-ответе."""
        if depth > 8:
            return []

        prices = []

        if isinstance(data, dict):
            for key, value in data.items():
                key_lower = key.lower()
                # Ключи, которые могут содержать цену
                if any(k in key_lower for k in (
                    "price", "rate", "amount", "total", "cost",
                    "min_price", "max_price", "daily_price",
                )):
                    if isinstance(value, (int, float)) and 1000 <= value <= 1_000_000:
                        prices.append(int(value))
                    elif isinstance(value, str):
                        p = self.parse_price_text(value)
                        if p is not None:
                            prices.append(p)
                # Рекурсия
                if isinstance(value, (dict, list)):
                    prices.extend(self._extract_prices_from_json(value, depth + 1))

        elif isinstance(data, list):
            for item in data[:50]:  # Лимит чтобы не зациклиться
                if isinstance(item, (dict, list)):
                    prices.extend(self._extract_prices_from_json(item, depth + 1))

        return prices

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Островок работает через перехват API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
