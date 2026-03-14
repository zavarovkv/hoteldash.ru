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

        # Дампим body HTML для отладки
        body_html = await page.evaluate("() => document.body ? document.body.innerHTML.substring(0, 3000) : 'NO BODY'")
        logger.info("[%s] BODY HTML: %s", self.source_name, body_html[:2000])

        # Считаем все элементы
        element_count = await page.evaluate("() => document.body ? document.body.querySelectorAll('*').length : 0")
        button_count = await page.evaluate("() => document.body ? document.body.querySelectorAll('button').length : 0")
        logger.info("[%s] Всего элементов: %d, кнопок: %d", self.source_name, element_count, button_count)

        # Проверяем все элементы включая Shadow DOM
        shadow_info = await page.evaluate("""() => {
            var result = [];
            document.querySelectorAll('*').forEach(el => {
                if (el.shadowRoot) result.push(el.tagName + '.' + (el.className || '').substring(0, 50));
            });
            return result;
        }""")
        logger.info("[%s] Элементы с Shadow DOM: %s", self.source_name, shadow_info)

        # Находим элемент "Найти" (это не <button>, а <a> или <div>)
        try:
            # Найдём элемент через JS по тексту
            find_el_info = await page.evaluate("""() => {
                var all = document.querySelectorAll('*');
                for (var el of all) {
                    if (el.childNodes.length <= 3) {
                        var text = el.textContent.trim();
                        if (text === 'Найти' || text === 'Search') {
                            return {tag: el.tagName, class: el.className.substring(0, 100), id: el.id};
                        }
                    }
                }
                return null;
            }""")
            logger.info("[%s] Элемент 'Найти': %s", self.source_name, find_el_info)

            if find_el_info:
                # Кликаем по тексту через locator
                search_el = page.get_by_text("Найти", exact=True)
                await search_el.click(timeout=10000)
                logger.info("[%s] 'Найти' нажата", self.source_name)
            else:
                logger.warning("[%s] Элемент 'Найти' не найден", self.source_name)
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
                        # Ищем конкретно цену с ₽ в тексте
                        rub_match = re.search(r'([\d\s\u2009]+)\s*₽', text)
                        if rub_match:
                            price_str = rub_match.group(1) + '₽'
                            price = self.parse_price_text(price_str)
                            if price is not None:
                                return ParseResult(price=price, raw_text=price_str.strip(), error=None)
                        # Fallback: весь текст
                        price = self.parse_price_text(text)
                        if price is not None:
                            return ParseResult(price=price, raw_text=text[:100], error=None)
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
