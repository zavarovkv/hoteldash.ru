"""Оркестрация: запуск всех парсеров для всех отелей."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, datetime, timedelta
from typing import Optional

from src.config_loader import load_config, build_url, get_checkin_dates
from src.db import get_session
from src.models import Hotel, Price, ScrapeRun
from src.parsers.ostrovok import OstrovokParser
from src.parsers.tbank import TbankParser
from src.parsers.onetwotrip import OneTwoTripParser
from src.parsers.yandex_travel import YandexTravelParser
from src.parsers.avito import AvitoParser
from src.parsers.hotel_site import HotelSiteParser
from src.utils.browser import create_browser, create_context
from src.utils.antibot import delay_between_pages, delay_between_hotels, shuffle_items
from src.utils.notifications import notify_scrape_complete, notify_error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

PARSERS = {
    "ostrovok": OstrovokParser,
    "tbank": TbankParser,
    "onetwotrip": OneTwoTripParser,
    "yandex_travel": YandexTravelParser,
    "avito": AvitoParser,
    "hotel_site": HotelSiteParser,
}


def ensure_hotel_in_db(session, hotel_config) -> int:
    """Создаёт отель в БД если не существует. Возвращает hotel_id."""
    hotel = session.query(Hotel).filter_by(slug=hotel_config.slug).first()
    if hotel:
        return hotel.id
    hotel = Hotel(
        name=hotel_config.name,
        city=hotel_config.city,
        stars=hotel_config.stars,
        slug=hotel_config.slug,
        website=hotel_config.website,
    )
    session.add(hotel)
    session.flush()
    return hotel.id


async def run_scraping(
    hotel_slug: Optional[str] = None,
    source_filter: Optional[str] = None,
    checkin_override: Optional[str] = None,
):
    """Основной цикл скрейпинга."""
    config = load_config()

    # Начало scrape_run
    with get_session() as session:
        run = ScrapeRun(started_at=datetime.utcnow())
        session.add(run)
        session.flush()
        run_id = run.id

    total_tasks = 0
    successful = 0
    failed = 0

    hotels = config.hotels
    if hotel_slug:
        hotels = [h for h in hotels if h.slug == hotel_slug]
        if not hotels:
            logger.error("Отель '%s' не найден в конфигурации", hotel_slug)
            return

    # Определяем даты
    if checkin_override:
        checkin_dates = [date.fromisoformat(checkin_override)]
    else:
        checkin_dates = get_checkin_dates(config.schedule.checkin_offsets_days)

    nights = config.schedule.nights
    adults = config.schedule.adults

    # Рандомизируем порядок
    hotels = shuffle_items(hotels)

    try:
        async with create_browser() as browser:
            for hotel_config in hotels:
                with get_session() as session:
                    hotel_id = ensure_hotel_in_db(session, hotel_config)

                sources = hotel_config.sources
                if source_filter:
                    sources = [s for s in sources if s.name == source_filter]
                    if not sources:
                        logger.warning(
                            "Источник '%s' не найден для отеля '%s'",
                            source_filter, hotel_config.slug,
                        )
                        continue

                # Рандомизируем порядок источников
                sources = shuffle_items(sources)

                for source_config in sources:
                    parser_class = PARSERS.get(source_config.name)
                    if not parser_class:
                        logger.warning("Нет парсера для источника: %s", source_config.name)
                        continue

                    parser = parser_class(widget=source_config.widget) if source_config.name == "hotel_site" else parser_class()
                    context = await create_context(browser)

                    try:
                        for checkin in checkin_dates:
                            checkout = checkin + timedelta(days=nights)
                            total_tasks += 1

                            # Новая страница для каждой даты — чистый стейт
                            page = await context.new_page()
                            try:
                                if source_config.has_dates:
                                    url = build_url(source_config.url_template, checkin, checkout, nights, adults)
                                else:
                                    url = source_config.url_template

                                result = await parser.scrape(
                                    page, url, hotel_config.slug, checkin.isoformat()
                                )

                                # Сохраняем результат
                                with get_session() as session:
                                    price_record = Price(
                                        hotel_id=hotel_id,
                                        source=source_config.name,
                                        checkin_date=checkin,
                                        nights=nights,
                                        price=result.price,
                                        currency="RUB",
                                        raw_price_text=result.raw_text,
                                        error=result.error,
                                    )
                                    session.add(price_record)

                                if result.price is not None:
                                    successful += 1
                                else:
                                    failed += 1
                            finally:
                                await page.close()

                            await delay_between_pages()

                    finally:
                        await context.close()

                await delay_between_hotels()

        status = "completed"

    except Exception:
        status = "error"
        raise

    finally:
        # Всегда обновляем scrape_run — даже при краше
        with get_session() as session:
            run = session.get(ScrapeRun, run_id)
            if run:
                run.finished_at = datetime.utcnow()
                run.total_tasks = total_tasks
                run.successful = successful
                run.failed = failed
                run.status = status

    logger.info(
        "Скрейпинг завершён: %d/%d успешно, %d ошибок",
        successful, total_tasks, failed,
    )

    notify_scrape_complete(successful, failed, total_tasks)


def main():
    """Точка входа для запуска из командной строки."""
    import argparse

    parser = argparse.ArgumentParser(description="HotelDash — парсер цен на отели")
    parser.add_argument("--hotel", help="Slug отеля (парсить только один отель)")
    parser.add_argument("--source", help="Источник (парсить только один OTA)")
    parser.add_argument("--checkin", help="Дата заезда (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        asyncio.run(run_scraping(
            hotel_slug=args.hotel,
            source_filter=args.source,
            checkin_override=args.checkin,
        ))
    except Exception as e:
        logger.exception("Критическая ошибка")
        notify_error(str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
