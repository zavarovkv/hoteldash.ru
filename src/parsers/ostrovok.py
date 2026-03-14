"""Парсер Островок (ostrovok.ru) — перехват API-ответов через Playwright."""

from __future__ import annotations

import logging
from typing import Optional

from playwright.async_api import Page, Response

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

# Максимальное время ожидания API-ответа (мс)
_API_WAIT_MAX_MS = 15_000
_API_POLL_INTERVAL_MS = 500


class OstrovokParser(BaseParser):
    source_name = "ostrovok"
    needs_browser = True

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы с ценами вместо парсинга DOM."""
        captured_prices: list[int] = []

        async def on_response(response: Response):
            try:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or "json" not in content_type:
                    return

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

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[%s] goto timeout (ожидаемо для SPA): %s", self.source_name, type(e).__name__)

        # Ждём API-ответ с ценами — поллинг вместо фиксированного ожидания
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

    def _extract_room_prices(self, data) -> list[int]:
        """Извлекает цены номеров из ответа /hp/search API Островка."""
        if not isinstance(data, dict):
            return []

        # Островок возвращает тарифы в ключе "rates"
        rates = data.get("rates")
        if not isinstance(rates, list) or not rates:
            return []

        prices = []
        for rate in rates:
            price = self._get_rate_price(rate)
            if price is not None:
                prices.append(price)

        return prices

    def _get_rate_price(self, rate: dict) -> Optional[int]:
        """Извлекает цену из объекта тарифа Островка."""
        if not isinstance(rate, dict):
            return None

        # Основной путь: payment_options.payment_types[0].show_amount
        payment_options = rate.get("payment_options")
        if isinstance(payment_options, dict):
            payment_types = payment_options.get("payment_types")
            if isinstance(payment_types, list) and payment_types:
                pt = payment_types[0]
                if isinstance(pt, dict):
                    for key in ("show_amount", "amount"):
                        val = pt.get(key)
                        price = self._parse_price_value(val)
                        if price is not None:
                            return price

        # Фоллбэк: прямые ключи на уровне тарифа
        for key in ("total_price", "sell_price", "price", "min_price"):
            val = rate.get(key)
            price = self._parse_price_value(val)
            if price is not None:
                return price

        return None

    @staticmethod
    def _parse_price_value(val) -> Optional[int]:
        """Конвертирует значение цены (int/float/str) в целое число."""
        if val is None:
            return None
        try:
            price = int(float(val))
            if 5000 <= price <= 1_000_000:
                return price
        except (ValueError, TypeError, OverflowError):
            pass
        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Островок работает через перехват API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
