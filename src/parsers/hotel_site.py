"""Парсер сайта отеля (TravelLine / Bnovo виджет)."""

from __future__ import annotations

import logging
import re
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: Optional[str] = None):
        self.widget = widget  # 'travelline', 'bnovo', etc.

    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает цену со страницы TravelLine booking engine."""
        # Ждём загрузку TravelLine React SPA
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(5000)

        # Дампим HTML страницы для отладки
        html_dump = await page.evaluate("() => document.documentElement.outerHTML.substring(0, 3000)")
        logger.info("[%s] HTML страницы: %s", self.source_name, html_dump[:1500])

        # Проверяем все элементы включая Shadow DOM
        shadow_info = await page.evaluate("""() => {
            var result = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot) result.push(el.tagName + '.' + (el.className || '').substring(0, 50));
            });
            return result;
        }""")
        logger.info("[%s] Элементы с Shadow DOM: %s", self.source_name, shadow_info)

        # Нажимаем кнопку "Найти" через locator (пронизывает Shadow DOM)
        try:
            search_btn = page.get_by_role("button", name=re.compile(r"найти|search|find", re.IGNORECASE))
            if await search_btn.count() > 0:
                await search_btn.first.click()
                logger.info("[%s] Кнопка 'Найти' нажата через locator", self.source_name)
            else:
                # Fallback: ищем по тексту
                btn = page.locator("button").filter(has_text=re.compile(r"найти|search", re.IGNORECASE))
                if await btn.count() > 0:
                    await btn.first.click()
                    logger.info("[%s] Кнопка 'Найти' нажата через text filter", self.source_name)
                else:
                    logger.warning("[%s] Кнопка 'Найти' не найдена", self.source_name)
        except Exception as e:
            logger.warning("[%s] Ошибка при клике 'Найти': %s", self.source_name, e)

        # Ждём загрузку результатов
        await page.wait_for_timeout(15000)

        # Скриншот для отладки
        await self._save_screenshot(page, "tl_debug", "after_search")

        # Ищем цены через locator (пронизывает Shadow DOM)
        price_locators = [
            page.locator("[class*='price']"),
            page.locator("[class*='cost']"),
            page.locator("[class*='amount']"),
            page.locator("[class*='rate']"),
        ]

        for loc in price_locators:
            try:
                count = await loc.count()
                for i in range(min(count, 20)):
                    try:
                        text = await loc.nth(i).inner_text(timeout=2000)
                        text = text.strip()
                        if not text:
                            continue
                        price = self.parse_price_text(text)
                        if price is not None:
                            return ParseResult(price=price, raw_text=text, error=None)
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: ищем ₽ по тексту через locator
        try:
            rub_elements = page.locator(":text('₽')")
            count = await rub_elements.count()
            logger.info("[%s] Элементов с ₽: %d", self.source_name, count)
            for i in range(min(count, 10)):
                try:
                    text = await rub_elements.nth(i).inner_text(timeout=2000)
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text.strip(), error=None)
                except Exception:
                    continue
        except Exception:
            pass

        # Ещё fallback: ищем через JS рекурсивно по Shadow DOM
        try:
            price_text = await page.evaluate("""() => {
                function findPriceInShadow(root) {
                    if (!root) return null;
                    var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                    while (walker.nextNode()) {
                        var text = walker.currentNode.textContent;
                        if (text && text.match(/\\d[\\d\\s]*₽/)) return text.trim();
                    }
                    var children = root.querySelectorAll('*');
                    for (var child of children) {
                        if (child.shadowRoot) {
                            var result = findPriceInShadow(child.shadowRoot);
                            if (result) return result;
                        }
                    }
                    return null;
                }
                return findPriceInShadow(document) || findPriceInShadow(document.body);
            }""")
            if price_text:
                logger.info("[%s] Найдена цена в Shadow DOM: %s", self.source_name, price_text[:100])
                price = self.parse_price_text(price_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=price_text, error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
