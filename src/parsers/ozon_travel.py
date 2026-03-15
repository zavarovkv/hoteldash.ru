"""Парсер Ozon Travel — перехват API-ответов через Camoufox."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import random
import re
from typing import Optional

from playwright.async_api import Page, Response

from src.parsers.base import BaseParser, ParseResult
from src.utils.browser import _parse_proxy_url

logger = logging.getLogger(__name__)

_API_WAIT_MAX_MS = 30_000
_API_POLL_INTERVAL_MS = 500
_MAX_RETRIES = 5
_RETRY_DELAY_SEC = 95


class OzonTravelParser(BaseParser):
    source_name = "ozon_travel"
    needs_browser = True
    use_camoufox = True

    @property
    def proxy_url(self) -> Optional[str]:
        return os.getenv("OZON_PROXY_URL")

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Перехватывает API-ответы с ценами."""
        captured_prices: list[int] = []
        async def on_response(response: Response):
            try:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or "json" not in content_type:
                    return

                resp_url = response.url

                skip = (".js", ".css", ".png", ".jpg", ".svg", ".woff", ".ico",
                        ".gif", ".webp", ".ttf", ".eot")
                if any(resp_url.endswith(s) or (s + "?") in resp_url for s in skip):
                    return

                body = await response.json()

                # Извлекаем цены из widgetStates (stringified JSON)
                if "entrypoint-api.bx/page/json" in resp_url and isinstance(body, dict):
                    ws_prices = self._extract_from_widget_states(body)
                    if ws_prices:
                        logger.info(
                            "[%s] widgetStates → %d цен найдено",
                            self.source_name, len(ws_prices),
                        )
                        captured_prices.extend(ws_prices)

                # Стандартный рекурсивный поиск
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

        # Блокируем тяжёлые ресурсы для экономии трафика прокси
        async def block_heavy(route):
            await route.abort()

        await page.route("**/*.{png,jpg,jpeg,gif,webp,svg,ico,woff,woff2,ttf,eot,mp4,webm}", block_heavy)
        await page.route("**/{analytics,tracking,metrics,mc.yandex,google-analytics,gtm}*", block_heavy)
        await page.route("**/static/css/**", block_heavy)

        logger.info(
            "[%s] %s | checkin=%s",
            self.source_name, hotel_slug, checkin_date,
        )

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[%s] goto error: %s: %s", self.source_name, type(e).__name__, str(e)[:200])

        await page.wait_for_timeout(3000)

        try:
            title = await page.title()
            logger.info("[%s] Страница: title='%s', url=%s", self.source_name, title, page.url[:120])
        except Exception:
            title = ""
            logger.warning("[%s] Не удалось получить title, url=%s", self.source_name, page.url[:120])

        # Детекция капчи/блокировки
        if title and ("captcha" in title.lower() or "доступ ограничен" in title.lower()):
            return ParseResult(price=None, raw_text=None, error=f"captcha: {title}")

        # Скролл для загрузки тарифов
        for _ in range(3):
            await page.evaluate("window.scrollBy(0, 500)")
            await page.wait_for_timeout(1000)

        # Поллинг — ждём API-ответ с ценами (обычно приходит из widgetStates)
        waited = 0
        while not captured_prices and waited < _API_WAIT_MAX_MS:
            await page.wait_for_timeout(_API_POLL_INTERVAL_MS)
            waited += _API_POLL_INTERVAL_MS

        if captured_prices:
            min_price = min(captured_prices)
            logger.info(
                "[%s] %s | %s | мін. цена: %d руб. (из %d вариантов)",
                self.source_name, hotel_slug, checkin_date,
                min_price, len(captured_prices),
            )
            return ParseResult(
                price=min_price,
                raw_text=f"{min_price} ₽",
                error=None,
            )

        return ParseResult(price=None, raw_text=None, error="no prices in API responses")

    async def scrape_with_own_browser(self, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Запускает Camoufox и парсит с retry при капче."""
        for attempt in range(1, _MAX_RETRIES + 1):
            result = await self._try_scrape(url, hotel_slug, checkin_date)
            if result.price is not None:
                return result

            # Проверяем — капча или просто нет цен
            is_captcha = result.error and "captcha" in result.error.lower()
            if not is_captcha:
                return result

            if attempt < _MAX_RETRIES:
                logger.info(
                    "[%s] Капча, retry %d/%d через %dс (ждём новый IP)...",
                    self.source_name, attempt, _MAX_RETRIES, _RETRY_DELAY_SEC,
                )
                await asyncio.sleep(_RETRY_DELAY_SEC)

        return result

    _PROFILES = [
        {"os": "windows", "viewport": {"width": 1920, "height": 1080}, "locale": "ru-RU"},
        {"os": "windows", "viewport": {"width": 1536, "height": 864}, "locale": "ru-RU"},
        {"os": "windows", "viewport": {"width": 1366, "height": 768}, "locale": "ru-RU"},
        {"os": "macos", "viewport": {"width": 1440, "height": 900}, "locale": "ru-RU"},
        {"os": "macos", "viewport": {"width": 1680, "height": 1050}, "locale": "ru-RU"},
        {"os": "linux", "viewport": {"width": 1920, "height": 1080}, "locale": "ru-RU"},
    ]

    _REFERRERS = [
        "https://www.google.com/",
        "https://yandex.ru/",
        "https://www.google.ru/",
        "https://yandex.ru/search/?text=отель+метрополь+москва",
        "https://www.google.com/search?q=metropol+hotel+moscow",
    ]

    async def _try_scrape(self, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Одна попытка скрейпинга через Camoufox."""
        from camoufox.async_api import AsyncCamoufox

        proxy_raw = self.proxy_url
        proxy_config = _parse_proxy_url(proxy_raw) if proxy_raw else None

        profile = random.choice(self._PROFILES)
        referrer = random.choice(self._REFERRERS)

        logger.info("[%s] Camoufox %s %dx%d proxy: %s", self.source_name,
                     profile["os"], profile["viewport"]["width"], profile["viewport"]["height"],
                     proxy_raw.split("@")[-1] if proxy_raw else "нет")

        async with AsyncCamoufox(
            headless=True,
            proxy=proxy_config,
            os=profile["os"],
        ) as browser:
            page = await browser.new_page()
            await page.set_viewport_size(profile["viewport"])
            await page.set_extra_http_headers({
                "Accept-Language": random.choice([
                    "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
                    "ru,en-US;q=0.9,en;q=0.8",
                    "ru-RU,ru;q=0.9",
                ]),
                "Referer": referrer,
            })
            try:
                return await self.scrape(page, url, hotel_slug, checkin_date)
            finally:
                await page.close()

    def _extract_from_widget_states(self, body: dict) -> list[int]:
        """Парсит widgetStates — значения являются stringified JSON."""
        prices = []
        widget_states = body.get("widgetStates")
        if not isinstance(widget_states, dict):
            return prices

        for widget_key, widget_val in widget_states.items():
            if not isinstance(widget_val, str):
                continue
            # Только виджеты, связанные с отелями/номерами/тарифами
            key_lower = widget_key.lower()
            if not any(k in key_lower for k in ("hotel", "room", "tariff", "price", "travel")):
                continue
            try:
                parsed = json.loads(widget_val)
                self._find_prices_recursive(parsed, prices, depth=0)
            except (json.JSONDecodeError, TypeError):
                pass

        return prices

    def _extract_prices(self, data) -> list[int]:
        """Извлекает цены из JSON-ответа Ozon Travel API."""
        prices = []
        self._find_prices_recursive(data, prices, depth=0)
        return prices

    def _find_prices_recursive(self, obj, prices: list[int], depth: int):
        """Рекурсивно ищет цены в JSON-структуре."""
        if depth > 15 or len(prices) > 200:
            return

        if isinstance(obj, dict):
            for key, value in obj.items():
                key_lower = key.lower()
                if any(k in key_lower for k in ("price", "amount", "cost", "total")):
                    p = self._try_parse_price(value)
                    if p is not None:
                        prices.append(p)

                # Пробуем распарсить stringified JSON в значениях
                if isinstance(value, str) and len(value) > 10 and value.startswith(("{", "[")):
                    try:
                        parsed = json.loads(value)
                        self._find_prices_recursive(parsed, prices, depth + 1)
                    except (json.JSONDecodeError, TypeError):
                        pass

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
        # Пробуем строку с пробелами/символами: "26 100 ₽"
        if isinstance(val, str):
            cleaned = re.sub(r"[^\d]", "", val)
            if cleaned:
                try:
                    price = int(cleaned)
                    if 5000 <= price <= 1_000_000:
                        return price
                except (ValueError, OverflowError):
                    pass
        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Ozon работает через перехват API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
