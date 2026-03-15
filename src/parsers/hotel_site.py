"""Парсер сайта отеля (TravelLine / Bnovo виджет)."""

from __future__ import annotations

import logging
import re
from datetime import date as date_type, timedelta
from typing import Optional

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: Optional[str] = None):
        self.widget = widget  # 'travelline', 'bnovo', etc.
        self._checkin: Optional[date_type] = None
        self._checkout: Optional[date_type] = None

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Сохраняет даты и делегирует базовому scrape."""
        self._checkin = date_type.fromisoformat(checkin_date)
        self._checkout = self._checkin + timedelta(days=1)
        return await super().scrape(page, url, hotel_slug, checkin_date)

    async def _set_dates(self, page: Page) -> None:
        """Явно устанавливает даты в виджете TravelLine через date picker."""
        if not self._checkin or not self._checkout:
            return

        checkin_str = self._checkin.strftime("%d.%m.%Y")
        checkout_str = self._checkout.strftime("%d.%m.%Y")

        # Находим все input-ы с датами (формат DD.MM.YYYY) и помечаем их
        count = await page.evaluate("""() => {
            const inputs = document.querySelectorAll('input');
            let idx = 0;
            for (const input of inputs) {
                const val = input.value || '';
                const ph = (input.placeholder || '').toLowerCase();
                const name = (input.name || '').toLowerCase();
                if (/^\\d{2}\\.\\d{2}\\.\\d{4}$/.test(val) ||
                    ph.includes('заезд') || ph.includes('выезд') ||
                    ph.includes('дата') || name.includes('date') ||
                    name.includes('arrival') || name.includes('departure')) {
                    input.setAttribute('data-hd-date', idx.toString());
                    idx++;
                }
            }
            return idx;
        }""")

        if count >= 2:
            # Заезд
            arrival = page.locator("[data-hd-date='0']")
            await arrival.click()
            await arrival.fill(checkin_str)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

            # Выезд
            departure = page.locator("[data-hd-date='1']")
            await departure.click()
            await departure.fill(checkout_str)
            await page.keyboard.press("Escape")
            await page.wait_for_timeout(300)

            logger.info("[%s] Даты установлены: %s — %s", self.source_name, checkin_str, checkout_str)
        elif count == 1:
            arrival = page.locator("[data-hd-date='0']")
            await arrival.click()
            await arrival.fill(checkin_str)
            await page.keyboard.press("Escape")
            logger.info("[%s] Установлена дата заезда: %s", self.source_name, checkin_str)
        else:
            # Fallback: пробуем через JS триплклик + ввод на первых двух видимых input
            logger.warning("[%s] Поля дат не найдены, пробуем fallback", self.source_name)
            try:
                await page.evaluate("""(dates) => {
                    const [checkin, checkout] = dates;
                    const inputs = document.querySelectorAll('input[type="text"], input:not([type])');
                    const visible = [];
                    for (const inp of inputs) {
                        const rect = inp.getBoundingClientRect();
                        if (rect.width > 0 && rect.height > 0) visible.push(inp);
                    }
                    if (visible.length >= 2) {
                        const setter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        setter.call(visible[0], checkin);
                        visible[0].dispatchEvent(new Event('input', {bubbles: true}));
                        visible[0].dispatchEvent(new Event('change', {bubbles: true}));
                        setter.call(visible[1], checkout);
                        visible[1].dispatchEvent(new Event('input', {bubbles: true}));
                        visible[1].dispatchEvent(new Event('change', {bubbles: true}));
                    }
                }""", [checkin_str, checkout_str])
            except Exception as e:
                logger.warning("[%s] Fallback установки дат не удался: %s", self.source_name, e)

    async def _extract_price(self, page: Page) -> ParseResult:
        """Извлекает минимальную цену со страницы TravelLine booking engine."""
        # Ждём загрузку TravelLine React SPA
        try:
            await page.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        await page.wait_for_timeout(3000)

        # Явно устанавливаем даты в виджете
        await self._set_dates(page)

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
