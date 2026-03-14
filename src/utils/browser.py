"""Управление Playwright-браузером с anti-detect настройками."""

import os
import logging
from contextlib import asynccontextmanager
from typing import Optional

from playwright.async_api import async_playwright, Browser, BrowserContext
from fake_useragent import UserAgent

from config.settings import (
    VIEWPORT_WIDTH,
    VIEWPORT_HEIGHT,
    LOCALE,
    TIMEZONE,
    PAGE_LOAD_TIMEOUT,
)

logger = logging.getLogger(__name__)

ua = UserAgent()

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['ru-RU', 'ru', 'en-US', 'en']});
window.chrome = {runtime: {}};
"""


def _parse_proxy_url(raw: str) -> dict:
    """Парсит proxy URL 'user:pass@host:port' в dict для Playwright."""
    if "@" in raw:
        auth_part, server_part = raw.rsplit("@", 1)
        if "://" in auth_part:
            scheme, auth_part = auth_part.split("://", 1)
        else:
            scheme = "http"
        user, password = auth_part.split(":", 1)
        return {
            "server": f"{scheme}://{server_part}",
            "username": user,
            "password": password,
        }
    return {"server": raw if "://" in raw else f"http://{raw}"}


@asynccontextmanager
async def create_browser(proxy_url: Optional[str] = None):
    """Создаёт и возвращает браузер Playwright."""
    async with async_playwright() as p:
        effective_proxy = proxy_url or os.getenv("PROXY_URL")
        launch_args = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        }
        if effective_proxy:
            launch_args["proxy"] = _parse_proxy_url(effective_proxy)
            logger.info("Браузер запущен с прокси: %s", effective_proxy.split("@")[-1])

        browser = await p.chromium.launch(**launch_args)
        try:
            yield browser
        finally:
            await browser.close()


async def create_context(browser: Browser) -> BrowserContext:
    """Создаёт новый browser context с anti-detect настройками."""
    user_agent = ua.random

    context = await browser.new_context(
        user_agent=user_agent,
        viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT},
        locale=LOCALE,
        timezone_id=TIMEZONE,
        java_script_enabled=True,
    )

    await context.add_init_script(STEALTH_SCRIPT)
    context.set_default_timeout(PAGE_LOAD_TIMEOUT)

    logger.debug("Создан контекст браузера с UA: %s", user_agent)
    return context
