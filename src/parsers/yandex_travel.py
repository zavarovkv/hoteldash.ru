"""Парсер Яндекс Путешествия (travel.yandex.ru) — Camoufox + прокси."""

from __future__ import annotations

import asyncio
import logging
import os
import random
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult
from src.utils.browser import _parse_proxy_url

logger = logging.getLogger(__name__)

_MAX_RETRIES = 3
_RETRY_DELAY_SEC = 95

_PROFILES = [
    {"os": "windows", "viewport": {"width": 1920, "height": 1080}},
    {"os": "windows", "viewport": {"width": 1536, "height": 864}},
    {"os": "windows", "viewport": {"width": 1366, "height": 768}},
    {"os": "macos", "viewport": {"width": 1440, "height": 900}},
    {"os": "macos", "viewport": {"width": 1680, "height": 1050}},
]

_REFERRERS = [
    "https://www.google.com/",
    "https://yandex.ru/",
    "https://www.google.ru/",
    "https://yandex.ru/search/?text=отели+москва",
]


class YandexTravelParser(BaseParser):
    source_name = "yandex_travel"
    needs_browser = True
    use_camoufox = True

    @property
    def proxy_url(self) -> Optional[str]:
        return os.getenv("YANDEX_PROXY_URL") or os.getenv("OZON_PROXY_URL")

    async def scrape_with_own_browser(self, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Запускает Camoufox и парсит с retry при капче."""
        result = ParseResult(price=None, raw_text=None, error="no attempts")
        for attempt in range(1, _MAX_RETRIES + 1):
            result = await self._try_scrape(url, hotel_slug, checkin_date)
            if result.price is not None:
                return result

            is_captcha = result.error and "captcha" in result.error.lower()
            if not is_captcha:
                return result

            if attempt < _MAX_RETRIES:
                logger.info(
                    "[%s] Капча, retry %d/%d через %dс...",
                    self.source_name, attempt, _MAX_RETRIES, _RETRY_DELAY_SEC,
                )
                await asyncio.sleep(_RETRY_DELAY_SEC)

        return result

    async def _try_scrape(self, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Одна попытка скрейпинга через Camoufox."""
        from camoufox.async_api import AsyncCamoufox

        proxy_raw = self.proxy_url
        proxy_config = _parse_proxy_url(proxy_raw) if proxy_raw else None

        profile = random.choice(_PROFILES)
        referrer = random.choice(_REFERRERS)

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

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Загружает страницу и извлекает цену."""
        logger.info("[%s] %s | checkin=%s", self.source_name, hotel_slug, checkin_date)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            logger.warning("[%s] goto timeout: %s", self.source_name, type(e).__name__)

        await page.wait_for_timeout(3000)

        # Проверка капчи
        block_msg = await self._detect_block(page)
        if block_msg:
            logger.warning("[%s] Блокировка: %s", self.source_name, block_msg)
            return ParseResult(price=None, raw_text=None, error=f"blocked: {block_msg}")

        # Ждём загрузку цен SPA
        await page.wait_for_timeout(5000)

        return await self._extract_price(page)

    async def _detect_block(self, page: Page) -> Optional[str]:
        """Проверка на SmartCaptcha Яндекса."""
        captcha_selectors = [
            ".CheckboxCaptcha",
            ".SmartCaptcha",
            "[class*='SmartCaptcha']",
            "iframe[src*='smartcaptcha']",
            "[class*='captcha-wrapper']",
            "[class*='captcha']",
            "#captcha",
        ]
        for selector in captcha_selectors:
            if await page.query_selector(selector):
                return f"captcha detected ({selector})"

        try:
            body_text = await page.inner_text("body")
            block_phrases = ["нам нужно убедиться", "подтвердите, что вы не робот", "доступ ограничен"]
            for phrase in block_phrases:
                if phrase.lower() in body_text.lower():
                    return f"block phrase: {phrase}"
        except Exception:
            pass

        return None

    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает минимальную цену со страницы."""
        selectors = [
            "[class*='OfferPrice']",
            "[class*='offer-price']",
            "[class*='HotelPrice']",
            "[class*='hotel-price']",
            "[data-testid='offer-price']",
            "[class*='PriceBlock']",
            "[class*='price-block']",
            "[class*='MinPrice']",
            "[class*='min-price']",
        ]

        for selector in selectors:
            elements = await page.query_selector_all(selector)
            for element in elements[:5]:
                raw_text = await element.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Фоллбэк: поиск по символу ₽
        try:
            all_elements = await page.query_selector_all("span, div")
            for el in all_elements[:200]:
                text = await el.inner_text()
                text = text.strip()
                if ("₽" in text or "руб" in text.lower()) and len(text) < 30:
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text, error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
