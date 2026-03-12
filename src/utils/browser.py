"""Управление Playwright-браузером с anti-detect настройками."""

import os
import logging
from contextlib import asynccontextmanager

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


@asynccontextmanager
async def create_browser():
    """Создаёт и возвращает браузер Playwright."""
    async with async_playwright() as p:
        proxy_url = os.getenv("PROXY_URL")
        launch_args = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        }
        if proxy_url:
            launch_args["proxy"] = {"server": proxy_url}

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
