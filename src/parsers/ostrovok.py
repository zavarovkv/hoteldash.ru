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

                # Ловим только endpoint поиска номеров
                if "/hp/search" not in response.url:
                    return

                body = await response.json()
                prices = self._extract_room_prices(body)
                if prices:
                    logger.info(
                        "[%s] API %s → %d цен номеров",
                        self.source_name, response.url[:80], len(prices),
                    )
                    captured_prices.extend(prices)
                else:
                    logger.info(
                        "[%s] API %s → ответ без цен, ключи: %s",
                        self.source_name, response.url[:80],
                        list(body.keys())[:10] if isinstance(body, dict) else type(body).__name__,
                    )
            except Exception:
                pass

        page.on("response", on_response)

        logger.info(
            "[%s] %s | checkin=%s",
            self.source_name, hotel_slug, checkin_date,
        )

        # Навигация — таймаут не критичен, API-ответы могут прийти до полной загрузки
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[%s] goto timeout (ожидаемо для SPA): %s", self.source_name, type(e).__name__)

        # Ждём API-ответы с ценами
        await page.wait_for_timeout(15000)

        # Проверяем перехваченные цены
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

        return ParseResult(price=None, raw_text=None, error="no prices in API responses")

    def _extract_room_prices(self, data) -> list[int]:
        """Извлекает цены номеров из ответа /hp/search API Островка."""
        prices = []

        # Логируем структуру для диагностики
        if isinstance(data, dict):
            top_keys = list(data.keys())
            logger.debug("[%s] Структура ответа: %s", self.source_name, top_keys[:15])

            # Ищем массив номеров/тарифов в типичных ключах
            for key in ("rooms", "rates", "room_groups", "results", "offers",
                        "hotel_rates", "search_results", "data", "items"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    for item in items:
                        price = self._get_room_price(item)
                        if price is not None:
                            prices.append(price)
                    if prices:
                        return prices

            # Fallback: рекурсивный поиск по всем спискам
            for key, value in data.items():
                if isinstance(value, list) and len(value) > 0:
                    for item in value[:100]:
                        if isinstance(item, dict):
                            price = self._get_room_price(item)
                            if price is not None:
                                prices.append(price)
                    if prices:
                        return prices

        return prices

    def _get_room_price(self, room: dict) -> Optional[int]:
        """Извлекает цену из объекта номера/тарифа."""
        if not isinstance(room, dict):
            return None

        # Приоритетные ключи для цены номера за ночь/проживание
        price_keys = [
            "payment_options.payment_types.0.amount",  # вложенный путь
            "total_price", "daily_prices", "sell_price",
            "price", "amount", "rate", "cost",
            "min_price", "net_price", "gross_price",
        ]

        for key in price_keys:
            if "." in key:
                # Вложенный путь
                val = self._get_nested(room, key)
            else:
                val = room.get(key)

            if val is None:
                continue

            # Если это список цен (daily_prices), берём сумму или первый элемент
            if isinstance(val, list):
                if val and isinstance(val[0], (int, float)):
                    price = int(sum(val)) if len(val) <= 30 else int(val[0])
                    if 5000 <= price <= 1_000_000:
                        return price
                continue

            if isinstance(val, (int, float)):
                price = int(val)
                if 5000 <= price <= 1_000_000:
                    return price
            elif isinstance(val, str):
                # Сначала пробуем как число с десятичной точкой ("34200.00")
                try:
                    price = int(float(val))
                    if 5000 <= price <= 1_000_000:
                        return price
                except (ValueError, OverflowError):
                    pass
                # Фоллбэк: парсим как текст с валютой ("34 200 ₽")
                p = self.parse_price_text(val)
                if p is not None and 5000 <= p <= 1_000_000:
                    return p

        # Рекурсивный поиск в подобъектах номера
        for key, value in room.items():
            if isinstance(value, dict):
                price = self._get_room_price(value)
                if price is not None:
                    return price

        return None

    @staticmethod
    def _get_nested(data: dict, path: str):
        """Получает значение по вложенному пути 'a.b.0.c'."""
        current = data
        for part in path.split("."):
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    current = current[int(part)]
                except (IndexError, ValueError):
                    return None
            else:
                return None
        return current

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Островок работает через перехват API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
