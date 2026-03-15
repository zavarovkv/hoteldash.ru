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
        """Извлекает минимальную цену со страницы TravelLine booking engine."""
        # Ждём загрузку TravelLine React SPA
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # Нажимаем "Найти" для запуска поиска номеров
        try:
            search_el = page.get_by_text("Найти", exact=True)
            await search_el.click(timeout=10000)
            logger.info("[%s] Кнопка 'Найти' нажата", self.source_name)
        except Exception as e:
            logger.warning("[%s] Не удалось нажать 'Найти': %s", self.source_name, e)

        # Ждём загрузку результатов
        await page.wait_for_timeout(10000)

        # Собираем ВСЕ цены со страницы и берём минимальную
        all_prices: list[tuple[int, str]] = []  # (price, raw_text)

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
                for i in range(min(count, 30)):
                    try:
                        text = await loc.nth(i).inner_text(timeout=2000)
                        text = text.strip()
                        if not text:
                            continue
                        # Извлекаем все цены с ₽ из текста
                        for m in re.finditer(r'([\d\s\u2009]+)\s*₽', text):
                            price = self.parse_price_text(m.group(1) + '₽')
                            if price is not None and price >= 5000:
                                all_prices.append((price, m.group(0).strip()))
                    except Exception:
                        continue
            except Exception:
                continue

        # Fallback: ищем ₽ по тексту через locator
        if not all_prices:
            try:
                rub_elements = page.locator(":text('₽')")
                count = await rub_elements.count()
                logger.info("[%s] Элементов с ₽: %d", self.source_name, count)
                for i in range(min(count, 20)):
                    try:
                        text = await rub_elements.nth(i).inner_text(timeout=2000)
                        for m in re.finditer(r'([\d\s\u2009]+)\s*₽', text):
                            price = self.parse_price_text(m.group(1) + '₽')
                            if price is not None and price >= 5000:
                                all_prices.append((price, m.group(0).strip()))
                    except Exception:
                        continue
            except Exception:
                pass

        # Ещё fallback: ищем через JS рекурсивно по Shadow DOM
        if not all_prices:
            try:
                price_texts = await page.evaluate("""() => {
                    var results = [];
                    function findPricesInShadow(root) {
                        if (!root) return;
                        var walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
                        while (walker.nextNode()) {
                            var text = walker.currentNode.textContent.trim();
                            if (text && text.match(/\\d[\\d\\s]*₽/) && text.length < 50) {
                                results.push(text);
                            }
                        }
                        var children = root.querySelectorAll('*');
                        for (var child of children) {
                            if (child.shadowRoot) {
                                findPricesInShadow(child.shadowRoot);
                            }
                        }
                    }
                    findPricesInShadow(document);
                    findPricesInShadow(document.body);
                    return results;
                }""")
                for text in (price_texts or []):
                    for m in re.finditer(r'([\d\s\u2009]+)\s*₽', text):
                        price = self.parse_price_text(m.group(1) + '₽')
                        if price is not None and price >= 5000:
                            all_prices.append((price, m.group(0).strip()))
            except Exception:
                pass

        if all_prices:
            min_price, raw_text = min(all_prices, key=lambda x: x[0])
            logger.info(
                "[%s] Мин. цена: %d руб. (из %d найденных)",
                self.source_name, min_price, len(all_prices),
            )
            return ParseResult(price=min_price, raw_text=raw_text, error=None)

        return ParseResult(price=None, raw_text=None, error="price element not found")
