"""Парсер Ozon Travel — перехват API-ответов через Camoufox."""

from __future__ import annotations

import asyncio
import logging
import os
import random
import re
from typing import Optional

from playwright.async_api import Page

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
        """Загружает страницу и извлекает цену из DOM."""

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

        # Ждём рендеринг цен
        await page.wait_for_timeout(5000)

        # Извлекаем цену из DOM — ищем первый элемент с ₽
        return await self._extract_price_from_dom(page, hotel_slug, checkin_date)

    async def _extract_price_from_dom(self, page: Page, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Извлекает минимальную цену из DOM (текст с ₽)."""
        js = """() => {
            const ruble = String.fromCharCode(0x20BD);
            const results = [];
            const walker = document.createTreeWalker(
                document.body, NodeFilter.SHOW_TEXT, null, false
            );
            while (walker.nextNode()) {
                const text = walker.currentNode.textContent.trim();
                if (text && text.includes(ruble) && /[0-9]/.test(text) && text.length < 60) {
                    results.push(text);
                }
            }
            return results.slice(0, 30);
        }"""
        try:
            price_texts = await page.evaluate(js)
        except Exception as e:
            logger.warning("[%s] Не удалось извлечь цены из DOM: %s", self.source_name, e)
            return ParseResult(price=None, raw_text=None, error="DOM extraction failed")

        prices = []
        for text in price_texts:
            cleaned = re.sub(r"[^\d]", "", text)
            if cleaned:
                try:
                    price = int(cleaned)
                    if 5000 <= price <= 1_000_000:
                        prices.append(price)
                except (ValueError, OverflowError):
                    pass

        if prices:
            min_price = min(prices)
            logger.info(
                "[%s] %s | %s | мін. цена (DOM): %d руб. (из %d)",
                self.source_name, hotel_slug, checkin_date,
                min_price, len(prices),
            )
            return ParseResult(price=min_price, raw_text=f"{min_price} ₽", error=None)

        return ParseResult(price=None, raw_text=None, error="no prices in DOM")

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

    async def _extract_price(self, page: Page) -> ParseResult:
        """Не используется — Ozon работает через scrape override."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
