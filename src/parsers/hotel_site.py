"""Парсер сайта отеля — прямой вызов TravelLine API (без браузера)."""

from __future__ import annotations

import logging
from datetime import date as date_type, timedelta
from typing import Optional
from urllib.parse import urlparse, parse_qs

import httpx

from src.parsers.base import BaseParser, ParseResult

logger = logging.getLogger(__name__)

_API_URL = "https://ru-ibe.tlintegration.ru/ApiWebDistribution/BookingForm/hotel_availability"


class HotelSiteParser(BaseParser):
    source_name = "hotel_site"

    def __init__(self, widget: Optional[str] = None):
        self.widget = widget

    async def scrape(self, page, url: str, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Вызывает TravelLine API напрямую — браузер не используется."""
        checkin = date_type.fromisoformat(checkin_date)
        checkout = checkin + timedelta(days=1)

        # Извлекаем providerId и adults из URL
        params = parse_qs(urlparse(url).query)
        provider_id = params.get("providerId", [None])[0]
        if not provider_id:
            return ParseResult(price=None, raw_text=None, error="no providerId in URL")

        adults = int(params.get("adults", ["2"])[0])

        logger.info(
            "[%s] %s | checkin=%s | API direct (provider=%s)",
            self.source_name, hotel_slug, checkin_date, provider_id,
        )

        payload = {
            "criterions": [{
                "start_date": checkin.isoformat(),
                "end_date": checkout.isoformat(),
                "hotels": [{"code": provider_id}],
                "min_room_type_availability": 1,
                "ref": "0",
                "guests": [{"count": adults}],
            }],
            "include_all_placements": False,
            "include_promo_restricted": True,
            "include_rates": True,
            "include_transfers": True,
            "language": "ru-ru",
            "point_of_sale": {},
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(_API_URL, json=payload)
                if resp.status_code != 200:
                    return ParseResult(price=None, raw_text=None, error=f"API status {resp.status_code}")
                data = resp.json()
        except Exception as e:
            logger.error("[%s] API error: %s", self.source_name, e)
            return ParseResult(price=None, raw_text=None, error=f"API error: {e}")

        return self._parse_availability(data, hotel_slug, checkin_date)

    def _parse_availability(self, data: dict, hotel_slug: str, checkin_date: str) -> ParseResult:
        """Извлекает минимальную цену из ответа TravelLine API."""
        prices = []
        room_stays = data.get("room_stays", []) or data.get("data", {}).get("room_stays", [])

        for rs in room_stays:
            total = rs.get("total", {})
            price = total.get("price_after_tax")
            if isinstance(price, (int, float)) and 1000 <= price <= 1_000_000:
                prices.append(int(price))

        if prices:
            min_price = min(prices)
            logger.info(
                "[%s] %s | %s | мин. цена (API): %d руб. (из %d вариантов)",
                self.source_name, hotel_slug, checkin_date, min_price, len(prices),
            )
            return ParseResult(price=min_price, raw_text=f"{min_price} ₽", error=None)

        return ParseResult(price=None, raw_text=None, error="no prices in API response")

    async def _extract_price(self, page) -> ParseResult:
        """Не используется — TravelLine работает через прямой API."""
        return ParseResult(price=None, raw_text=None, error="use scrape override")
