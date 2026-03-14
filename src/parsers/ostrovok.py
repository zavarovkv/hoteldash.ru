"""Парсер Островок (ostrovok.ru) — HTTP-версия без браузера."""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

import httpx
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

ua = UserAgent()


class OstrovokParser(BaseParser):
    source_name = "ostrovok"
    needs_browser = False

    async def scrape_http(self, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Загружает страницу по HTTP и извлекает цену."""
        headers = {
            "User-Agent": ua.random,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
        }

        for attempt in range(1, 3):
            try:
                logger.info(
                    "[%s] %s | checkin=%s | попытка %d (HTTP)",
                    self.source_name, hotel_slug, checkin_date, attempt,
                )

                async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                    resp = await client.get(url, headers=headers)

                if resp.status_code != 200:
                    logger.warning("[%s] HTTP %d", self.source_name, resp.status_code)
                    if attempt < 2:
                        continue
                    return ParseResult(price=None, raw_text=None, error=f"HTTP {resp.status_code}")

                html = resp.text
                soup = BeautifulSoup(html, "html.parser")

                # 1. JSON-LD
                result = self._try_ld_json(soup)
                if result and result.price is not None:
                    logger.info(
                        "[%s] %s | %s | цена: %d руб. (ld+json)",
                        self.source_name, hotel_slug, checkin_date, result.price,
                    )
                    return result

                # 2. CSS-селекторы
                selectors = [
                    "[data-testid='price']",
                    "[class*='price-amount']",
                    "[class*='PriceAmount']",
                    "[class*='hotel-price']",
                    ".min-price",
                    "[class*='room-price'] [class*='amount']",
                    "[class*='RoomPrice'] [class*='Amount']",
                ]
                for selector in selectors:
                    el = soup.select_one(selector)
                    if el:
                        raw_text = el.get_text(strip=True)
                        price = self.parse_price_text(raw_text)
                        if price is not None:
                            logger.info(
                                "[%s] %s | %s | цена: %d руб.",
                                self.source_name, hotel_slug, checkin_date, price,
                            )
                            return ParseResult(price=price, raw_text=raw_text, error=None)

                # 3. Поиск ₽ в элементах с price/rate в классе
                for el in soup.select("[class*='price'], [class*='Price'], [class*='rate'], [class*='Rate']")[:10]:
                    text = el.get_text(strip=True)
                    if "₽" in text or "руб" in text.lower():
                        price = self.parse_price_text(text)
                        if price is not None:
                            logger.info(
                                "[%s] %s | %s | цена: %d руб.",
                                self.source_name, hotel_slug, checkin_date, price,
                            )
                            return ParseResult(price=price, raw_text=text, error=None)

                # 4. Поиск цены в любом тексте страницы
                rub_match = re.search(r'([\d\s\u00a0\u2009]+)\s*₽', html)
                if rub_match:
                    raw = rub_match.group(0).strip()
                    price = self.parse_price_text(raw)
                    if price is not None:
                        logger.info(
                            "[%s] %s | %s | цена: %d руб. (regex)",
                            self.source_name, hotel_slug, checkin_date, price,
                        )
                        return ParseResult(price=price, raw_text=raw, error=None)

                logger.warning("[%s] %s | %s | цена не найдена", self.source_name, hotel_slug, checkin_date)
                return ParseResult(price=None, raw_text=None, error="price element not found")

            except Exception as e:
                error_msg = f"{type(e).__name__}: {e}"
                logger.error(
                    "[%s] %s | %s | ошибка (попытка %d): %s",
                    self.source_name, hotel_slug, checkin_date, attempt, error_msg,
                )
                if attempt < 2:
                    continue
                return ParseResult(price=None, raw_text=None, error=error_msg)

        return ParseResult(price=None, raw_text=None, error="max retries exceeded")

    def _try_ld_json(self, soup: BeautifulSoup) -> Optional[ParseResult]:
        """Извлекает цену из JSON-LD разметки."""
        try:
            for script in soup.select('script[type="application/ld+json"]'):
                data = json.loads(script.string or "")
                offers = data.get("offers") or data.get("priceRange")
                if isinstance(offers, dict):
                    price_str = str(offers.get("price", ""))
                    if price_str:
                        price = self.parse_price_text(price_str)
                        if price is not None:
                            return ParseResult(price=price, raw_text=price_str, error=None)
                elif isinstance(offers, list):
                    for offer in offers:
                        price_str = str(offer.get("price", ""))
                        if price_str:
                            price = self.parse_price_text(price_str)
                            if price is not None:
                                return ParseResult(price=price, raw_text=price_str, error=None)
        except Exception:
            pass
        return None

    async def _extract_price(self, page) -> ParseResult:
        """Не используется — Островок работает через HTTP."""
        return ParseResult(price=None, raw_text=None, error="use scrape_http")
