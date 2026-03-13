"""Парсер сайта отеля (TravelLine виджет)."""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta

from playwright.async_api import Page

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: str | None = None):
        self.widget = widget  # 'travelline', 'bnovo', etc.

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Переопределяем scrape — TravelLine требует взаимодействия с формой."""
        from config.settings import MAX_RETRIES, RETRY_DELAY, SAVE_SCREENSHOTS_ON_ERROR

        checkin = date.fromisoformat(checkin_date)
        checkout = checkin + timedelta(days=1)

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(
                    "[%s] %s | checkin=%s | попытка %d",
                    self.source_name, hotel_slug, checkin_date, attempt,
                )

                await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                await page.wait_for_timeout(8000)

                # Ждём загрузку виджета бронирования
                widget_selector = self._get_widget_selector()
                try:
                    tl_form = await page.wait_for_selector(widget_selector, timeout=30000)
                    if tl_form:
                        await tl_form.scroll_into_view_if_needed()
                        await page.wait_for_timeout(2000)
                except Exception:
                    tl_form = None

                if not tl_form:
                    # Логируем что есть на странице для отладки
                    iframes = await page.query_selector_all("iframe")
                    logger.info("[%s] Найдено iframe: %d", self.source_name, len(iframes))
                    for i, iframe in enumerate(iframes[:5]):
                        src = await iframe.get_attribute("src") or "no-src"
                        logger.info("[%s] iframe[%d] src=%s", self.source_name, i, src)

                    forms = await page.query_selector_all("form, [id*='booking'], [class*='booking'], [id*='tl-'], [class*='tl-']")
                    logger.info("[%s] Элементов booking/tl: %d", self.source_name, len(forms))
                    for el in forms[:5]:
                        tag = await el.evaluate("e => e.tagName + '#' + (e.id || '') + '.' + (e.className || '')")
                        logger.info("[%s] элемент: %s", self.source_name, tag)

                    await self._save_screenshot(page, hotel_slug, checkin_date)

                    if attempt < MAX_RETRIES:
                        await page.wait_for_timeout(RETRY_DELAY * 1000)
                        continue
                    return ParseResult(
                        price=None, raw_text=None,
                        error=f"Widget not found (type={self.widget})",
                    )

                # Проверяем — виджет в iframe или inline
                iframe_selector = self._get_iframe_selector()
                tl_iframe = await page.query_selector(iframe_selector) if iframe_selector else None
                target = page

                if tl_iframe:
                    frame = await tl_iframe.content_frame()
                    if frame:
                        target = frame
                        await target.wait_for_load_state("domcontentloaded")
                        await target.wait_for_timeout(3000)

                # Заполняем даты
                filled = await self._fill_dates(target, checkin, checkout)
                if not filled:
                    if attempt < MAX_RETRIES:
                        await page.wait_for_timeout(RETRY_DELAY * 1000)
                        continue
                    return ParseResult(price=None, raw_text=None, error="failed to fill dates")

                # Ждём результаты
                await page.wait_for_timeout(5000)

                # Извлекаем цену
                result = await self._extract_price_from(target)

                if result.price is not None:
                    logger.info(
                        "[%s] %s | %s | цена: %d руб.",
                        self.source_name, hotel_slug, checkin_date, result.price,
                    )
                    return result

                # Если не нашли — пробуем в основном документе
                if target != page:
                    result = await self._extract_price_from(page)
                    if result.price is not None:
                        logger.info(
                            "[%s] %s | %s | цена: %d руб.",
                            self.source_name, hotel_slug, checkin_date, result.price,
                        )
                        return result

                if attempt < MAX_RETRIES:
                    await page.wait_for_timeout(RETRY_DELAY * 1000)
                    continue

                return result

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "[%s] %s | %s | исключение (попытка %d): %s",
                    self.source_name, hotel_slug, checkin_date, attempt, error_msg,
                )
                if SAVE_SCREENSHOTS_ON_ERROR:
                    await self._save_screenshot(page, hotel_slug, checkin_date)
                if attempt < MAX_RETRIES:
                    await page.wait_for_timeout(RETRY_DELAY * 1000)
                    continue
                return ParseResult(price=None, raw_text=None, error=error_msg)

        return ParseResult(price=None, raw_text=None, error="max retries exceeded")

    async def _fill_dates(self, target, checkin: date, checkout: date) -> bool:
        """Заполняет даты в TravelLine виджете."""
        checkin_str = checkin.strftime("%d.%m.%Y")
        checkout_str = checkout.strftime("%d.%m.%Y")

        try:
            # TravelLine обычно использует input[data-date] или input внутри формы
            date_inputs = await target.query_selector_all(
                "input[type='text'], input[name*='date'], input[name*='Date'], "
                "input[placeholder*='заезд'], input[placeholder*='выезд'], "
                "input[class*='date'], input[class*='Date'], "
                "[class*='tl-datepicker'] input, [class*='datepicker'] input"
            )

            if len(date_inputs) >= 2:
                await date_inputs[0].scroll_into_view_if_needed()
                await date_inputs[0].click(force=True)
                await date_inputs[0].fill("")
                await date_inputs[0].type(checkin_str, delay=50)
                await target.wait_for_timeout(500)

                await date_inputs[1].scroll_into_view_if_needed()
                await date_inputs[1].click(force=True)
                await date_inputs[1].fill("")
                await date_inputs[1].type(checkout_str, delay=50)
                await target.wait_for_timeout(500)

                # Нажимаем кнопку поиска
                search_btn = await target.query_selector(
                    "button[type='submit'], [class*='search-btn'], [class*='tl-btn'], "
                    "button[class*='booking'], input[type='submit']"
                )
                if search_btn:
                    await search_btn.scroll_into_view_if_needed()
                    await search_btn.click(force=True)
                    await target.wait_for_timeout(3000)

                return True

            # Альтернатива: TravelLine может использовать свой date picker
            # Пробуем кликнуть на элементы с датами
            date_elements = await target.query_selector_all(
                "[class*='checkin'], [class*='check-in'], "
                "[class*='arrival'], [data-type='checkin']"
            )
            if date_elements:
                await date_elements[0].click()
                await target.wait_for_timeout(1000)
                # Выбираем дату в календаре
                selected = await self._select_date_in_calendar(target, checkin)
                if selected:
                    await target.wait_for_timeout(1000)
                    # Checkout обычно выбирается автоматически после checkin
                    checkout_el = await target.query_selector(
                        "[class*='checkout'], [class*='check-out'], "
                        "[class*='departure'], [data-type='checkout']"
                    )
                    if checkout_el:
                        await checkout_el.click()
                        await target.wait_for_timeout(1000)
                        await self._select_date_in_calendar(target, checkout)
                    return True

            logger.warning("[%s] Не удалось найти поля дат", self.source_name)
            return False

        except Exception as e:
            logger.warning("[%s] Ошибка заполнения дат: %s", self.source_name, e)
            return False

    async def _select_date_in_calendar(self, target, target_date: date) -> bool:
        """Выбирает дату в календаре TravelLine."""
        day_str = str(target_date.day)
        try:
            # TravelLine calendar: td[data-day], td[data-date], div.day
            selectors = [
                f"td[data-day='{target_date.day}']",
                f"td[data-date='{target_date.isoformat()}']",
                f"[data-date='{target_date.strftime('%Y-%m-%d')}']",
            ]
            for sel in selectors:
                el = await target.query_selector(sel)
                if el:
                    await el.click()
                    return True

            # Fallback: ищем ячейку с числом дня
            cells = await target.query_selector_all("td, [class*='day']")
            for cell in cells:
                text = (await cell.inner_text()).strip()
                if text == day_str:
                    classes = await cell.get_attribute("class") or ""
                    if "disabled" not in classes and "past" not in classes:
                        await cell.click()
                        return True
        except Exception:
            pass
        return False

    def _get_widget_selector(self) -> str:
        """Возвращает CSS-селектор для ожидания виджета."""
        selectors = {
            "travelline": "#tl-booking-form, [class*='tl-booking'], iframe[src*='travelline']",
            "bnovo": "[class*='bnovo'], iframe[src*='bnovo'], #bnovo-widget",
        }
        return selectors.get(self.widget or "", "[class*='booking'], [class*='reservation']")

    def _get_iframe_selector(self) -> str | None:
        """Возвращает CSS-селектор iframe виджета."""
        selectors = {
            "travelline": "iframe[src*='travelline']",
            "bnovo": "iframe[src*='bnovo']",
        }
        return selectors.get(self.widget or "")

    async def _extract_price(self, page: Page) -> ParseResult:
        """Для совместимости с BaseParser (не используется напрямую)."""
        return await self._extract_price_from(page)

    async def _extract_price_from(self, target) -> ParseResult:
        """Извлекает цену из TravelLine результатов."""
        selectors = [
            "[class*='tl-room-price'], [class*='tl-price']",
            "[class*='room-price'], [class*='RoomPrice']",
            "[class*='price-value'], [class*='PriceValue']",
            "[class*='rate-price'], [class*='RatePrice']",
            "[class*='total-price'], [class*='TotalPrice']",
            "[class*='price'] [class*='amount']",
            "[class*='price'] [class*='value']",
        ]

        for selector in selectors:
            elements = await target.query_selector_all(selector)
            for el in elements:
                raw_text = await el.inner_text()
                raw_text = raw_text.strip()
                price = self.parse_price_text(raw_text)
                if price is not None:
                    return ParseResult(price=price, raw_text=raw_text, error=None)

        # Ищем по символу рубля
        try:
            all_elements = await target.query_selector_all(
                "[class*='price'], [class*='Price'], [class*='cost'], [class*='Cost'], "
                "[class*='rate'], [class*='Rate']"
            )
            for el in all_elements[:20]:
                text = await el.inner_text()
                if "₽" in text or "руб" in text.lower() or "RUB" in text:
                    price = self.parse_price_text(text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=text.strip(), error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
