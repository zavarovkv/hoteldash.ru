"""Парсер сайта отеля (TravelLine виджет)."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Optional

from playwright.async_api import Page, Frame

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: Optional[str] = None):
        self.widget = widget  # 'travelline', 'bnovo', etc.

    async def scrape(self, page: Page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Переопределяем scrape — TravelLine загружает контент в iframe."""
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
                await page.wait_for_timeout(10000)

                # TravelLine грузит виджет внутрь iframe (tlFrame...)
                tl_frame = await self._find_tl_frame(page)

                if not tl_frame:
                    logger.warning("[%s] TravelLine iframe не найден", self.source_name)
                    await self._save_screenshot(page, hotel_slug, checkin_date)
                    if attempt < MAX_RETRIES:
                        await page.wait_for_timeout(RETRY_DELAY * 1000)
                        continue
                    return ParseResult(price=None, raw_text=None, error="TravelLine iframe not found")

                logger.info("[%s] TravelLine iframe найден, URL: %s", self.source_name, tl_frame.url[:200])

                # Ждём загрузку контента iframe
                await tl_frame.wait_for_load_state("domcontentloaded")
                await page.wait_for_timeout(3000)

                # Логируем содержимое iframe
                frame_html = await tl_frame.evaluate("""() => {
                    return document.body ? document.body.innerHTML.substring(0, 1000) : 'NO BODY';
                }""")
                logger.info("[%s] iframe содержимое: %s", self.source_name, frame_html[:500])

                # Заполняем даты внутри iframe
                filled = await self._fill_dates_in_frame(tl_frame, checkin, checkout)
                if not filled:
                    # Даже без заполнения дат — TravelLine может показать цены по умолчанию
                    logger.info("[%s] Пробуем извлечь цены без заполнения дат", self.source_name)

                await page.wait_for_timeout(5000)

                # Извлекаем цену из iframe
                result = await self._extract_price_from_frame(tl_frame)

                if result.price is not None:
                    logger.info(
                        "[%s] %s | %s | цена: %d руб.",
                        self.source_name, hotel_slug, checkin_date, result.price,
                    )
                    return result

                if attempt < MAX_RETRIES:
                    await page.wait_for_timeout(RETRY_DELAY * 1000)
                    continue

                await self._save_screenshot(page, hotel_slug, checkin_date)
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

    async def _find_tl_frame(self, page: Page) -> Optional[Frame]:
        """Находит TravelLine iframe с реальным контентом."""
        # Логируем все frames для отладки
        logger.info("[%s] Все frames на странице (%d):", self.source_name, len(page.frames))
        for frame in page.frames:
            logger.info("[%s]   frame: name=%s url=%s", self.source_name, frame.name, (frame.url or "none")[:200])

        # Ищем iframe с реальным URL (не about:blank)
        best_frame = None
        for frame in page.frames:
            if frame == page.main_frame:
                continue
            url = frame.url or ""
            name = frame.name or ""
            is_tl = name.startswith("tlFrame") or "travelline" in url or "tlintegration" in url
            if is_tl and url and url != "about:blank":
                best_frame = frame
                # Не прерываем — берём последний (основной) iframe

        if best_frame:
            return best_frame

        # Fallback: ищем iframe по элементам DOM (с реальным src)
        tl_iframes = await page.query_selector_all("#tl-booking-form iframe[src], iframe[name^='tlFrame'][src]")
        for iframe_el in tl_iframes:
            src = await iframe_el.get_attribute("src") or ""
            if src and src != "about:blank":
                frame = await iframe_el.content_frame()
                if frame:
                    return frame

        return None

    async def _fill_dates_in_frame(self, frame: Frame, checkin: date, checkout: date) -> bool:
        """Заполняет даты внутри TravelLine iframe."""
        checkin_str = checkin.strftime("%d.%m.%Y")
        checkout_str = checkout.strftime("%d.%m.%Y")

        try:
            # Ищем все input внутри iframe
            all_inputs = await frame.query_selector_all("input")
            logger.info("[%s] Input'ов в iframe: %d", self.source_name, len(all_inputs))
            for i, inp in enumerate(all_inputs[:10]):
                inp_type = await inp.get_attribute("type") or ""
                inp_name = await inp.get_attribute("name") or ""
                inp_class = await inp.get_attribute("class") or ""
                inp_placeholder = await inp.get_attribute("placeholder") or ""
                logger.info(
                    "[%s]   input[%d]: type=%s name=%s class=%s placeholder=%s",
                    self.source_name, i, inp_type, inp_name, inp_class[:50], inp_placeholder,
                )

            # TravelLine date inputs
            date_inputs = await frame.query_selector_all(
                "input[class*='date'], input[name*='date'], input[name*='Date'], "
                "input[placeholder*='заезд'], input[placeholder*='выезд'], "
                "input[placeholder*='Заезд'], input[placeholder*='Выезд'], "
                "input[placeholder*='arrival'], input[placeholder*='departure'], "
                "[class*='datepicker'] input, [class*='tl-datepicker'] input"
            )

            if len(date_inputs) >= 2:
                logger.info("[%s] Найдены date input'ы: %d", self.source_name, len(date_inputs))
                await date_inputs[0].click(force=True)
                await frame.wait_for_timeout(500)
                await date_inputs[0].fill(checkin_str)
                await frame.wait_for_timeout(500)

                await date_inputs[1].click(force=True)
                await frame.wait_for_timeout(500)
                await date_inputs[1].fill(checkout_str)
                await frame.wait_for_timeout(500)

                # Ищем кнопку поиска
                search_btn = await frame.query_selector(
                    "button[type='submit'], button[class*='search'], "
                    "button[class*='btn'], input[type='submit'], "
                    "[class*='tl-btn'], [class*='search-button']"
                )
                if search_btn:
                    await search_btn.click(force=True)
                    await frame.wait_for_timeout(5000)

                return True

            # Альтернатива: TravelLine может использовать кликабельные div/span для дат
            date_elements = await frame.query_selector_all(
                "[class*='date'], [class*='checkin'], [class*='arrival'], "
                "[data-type='checkin'], [class*='calendar-input']"
            )
            if date_elements:
                logger.info("[%s] Кликабельных date-элементов: %d", self.source_name, len(date_elements))
                await date_elements[0].click(force=True)
                await frame.wait_for_timeout(2000)

                # Выбираем дату в календаре
                selected = await self._select_date_in_calendar(frame, checkin)
                if selected:
                    await frame.wait_for_timeout(2000)
                    return True

            logger.warning("[%s] Не удалось найти поля дат в iframe", self.source_name)
            return False

        except Exception as e:
            logger.warning("[%s] Ошибка заполнения дат: %s", self.source_name, e)
            return False

    async def _select_date_in_calendar(self, frame: Frame, target_date: date) -> bool:
        """Выбирает дату в календаре TravelLine."""
        day_str = str(target_date.day)
        try:
            selectors = [
                f"td[data-day='{target_date.day}']",
                f"td[data-date='{target_date.isoformat()}']",
                f"[data-date='{target_date.isoformat()}']",
            ]
            for sel in selectors:
                el = await frame.query_selector(sel)
                if el:
                    await el.click(force=True)
                    return True

            # Fallback: ищем ячейку с числом дня
            cells = await frame.query_selector_all("td, [class*='day']")
            for cell in cells:
                text = (await cell.inner_text()).strip()
                if text == day_str:
                    classes = await cell.get_attribute("class") or ""
                    if "disabled" not in classes and "past" not in classes:
                        await cell.click(force=True)
                        return True
        except Exception:
            pass
        return False

    def _get_widget_selector(self) -> str:
        """Возвращает CSS-селектор для ожидания виджета."""
        selectors = {
            "travelline": "#tl-booking-form, [class*='tl-booking'], iframe[name^='tlFrame']",
            "bnovo": "[class*='bnovo'], iframe[src*='bnovo'], #bnovo-widget",
        }
        return selectors.get(self.widget or "", "[class*='booking'], [class*='reservation']")

    def _get_iframe_selector(self) -> Optional[str]:
        """Возвращает CSS-селектор iframe виджета."""
        selectors = {
            "travelline": "iframe[src*='travelline'], iframe[name^='tlFrame']",
            "bnovo": "iframe[src*='bnovo']",
        }
        return selectors.get(self.widget or "")

    async def _extract_price(self, page: Page) -> ParseResult:
        """Для совместимости с BaseParser."""
        return await self._extract_price_from_frame(page)

    async def _extract_price_from_frame(self, target) -> ParseResult:
        """Извлекает цену из TravelLine iframe."""
        selectors = [
            "[class*='price']",
            "[class*='Price']",
            "[class*='cost']",
            "[class*='rate']",
            "[class*='amount']",
            "[class*='value']",
            "[class*='room'] [class*='sum']",
        ]

        for selector in selectors:
            try:
                elements = await target.query_selector_all(selector)
                for el in elements[:10]:
                    raw_text = await el.inner_text()
                    raw_text = raw_text.strip()
                    if not raw_text:
                        continue
                    if "₽" in raw_text or "руб" in raw_text.lower() or "RUB" in raw_text:
                        price = self.parse_price_text(raw_text)
                        if price is not None:
                            return ParseResult(price=price, raw_text=raw_text, error=None)
                    # Пробуем парсить даже без символа валюты
                    price = self.parse_price_text(raw_text)
                    if price is not None:
                        return ParseResult(price=price, raw_text=raw_text, error=None)
            except Exception:
                continue

        # Последний шанс — ищем любой текст с ₽
        try:
            all_text = await target.evaluate("""() => {
                return document.body ? document.body.innerText : '';
            }""")
            import re
            matches = re.findall(r'[\d\s]+₽', all_text)
            if matches:
                for match in matches[:5]:
                    price = self.parse_price_text(match)
                    if price is not None:
                        return ParseResult(price=price, raw_text=match.strip(), error=None)
        except Exception:
            pass

        return ParseResult(price=None, raw_text=None, error="price element not found")
