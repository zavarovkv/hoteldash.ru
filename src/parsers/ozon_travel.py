"""Парсер Ozon Travel — перехват API-ответов через Playwright."""

from __future__ import annotations

import json
import logging
from typing import Optional

from playwright.async_api import Page, Response

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

_API_WAIT_MAX_MS = 30_000
_API_POLL_INTERVAL_MS = 500


class OzonTravelParser(BaseParser):
    source_name = "ozon_travel"
    needs_browser = True

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы с ценами."""
        captured_prices: list[int] = []

        async def on_response(response: Response):
            try:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or "json" not in content_type:
                    return

                resp_url = response.url

                # Пропускаем статику, аналитику, рекламу
                skip = ("/static/", "/analytics", "/log", "/tracking", "/banner",
                        "/suggest", "/health", "google", "yandex", "mc.yandex")
                if any(s in resp_url for s in skip):
                    return

                body = await response.json()

                # Логируем все JSON-ответы для диагностики структуры API
                if isinstance(body, dict):
                    keys = list(body.keys())[:15]
                    logger.info(
                        "[%s] API %s → ключи: %s",
                        self.source_name, resp_url[:100], keys,
                    )

                    # Ищем цены в ответе
                    prices = self._extract_prices(body)
                    if prices:
                        logger.info(
                            "[%s] API %s → %d цен найдено",
                            self.source_name, resp_url[:100], len(prices),
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

        # Поллинг — ждём API-ответ с ценами
        waited = 0
        while not captured_prices and waited < _API_WAIT_MAX_MS:
            await page.wait_for_timeout(_API_POLL_INTERVAL_MS)
            waited += _API_POLL_INTERVAL_MS

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

        return ParseResult(price=None, raw_text=None, error="no prices in API responses")

    def _extract_prices(self, data: dict) -> list[int]:
        """Извлекает цены из JSON-ответа Ozon Travel API."""
        prices = []
        self._find_prices_recursive(data, prices, depth=0)
        return prices

    def _find_prices_recursive(self, obj, prices: list[int], depth: int):
        """Рекурсивно ищет цены в JSON-структуре."""
        if depth > 10 or len(prices) > 200:
            return

        if isinstance(obj, dict):
            # Ищем ключи, содержащие цену
            for key, value in obj.items():
                key_lower = key.lower()
                if any(k in key_lower for k in ("price", "amount", "cost", "total")):
                    p = self._try_parse_price(value)
                    if p is not None:
                        prices.append(p)

            # Рекурсия по значениям
            for value in obj.values():
                if isinstance(value, (dict, list)):
                    self._find_prices_recursive(value, prices, depth + 1)

        elif isinstance(obj, list):
            for item in obj[:50]:
                if isinstance(item, (dict, list)):
                    self._find_prices_recursive(item, prices, depth + 1)

    @staticmethod
    def _try_parse_price(val) -> Optional[int]:
        """Пробует извлечь цену из значения."""
        if val is None:
            return None
        try:
            price = int(float(val))
            if 5000 <= price <= 1_000_000:
                return price
        except (ValueError, TypeError, OverflowError):
            pass

        # Цена может быть в копейках (Ozon часто так делает)
        try:
            kopecks = int(float(val))
            price = kopecks // 100
            if 5000 <= price <= 1_000_000:
                return price
        except (ValueError, TypeError, OverflowError):
            pass

        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Ozon работает через перехват API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
