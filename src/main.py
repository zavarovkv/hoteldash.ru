"""Оркестрация: запуск всех парсеров для всех отелей."""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import date, timedelta
from typing import Optional

from src.config_loader import load_config, build_url, get_checkin_dates
from src.db import get_session
from src.models import Hotel, Price, ScrapeRun, now_moscow
from src.parsers.ostrovok import OstrovokParser
from src.parsers.hotel_site import HotelSiteParser
from src.parsers.ozon_travel import OzonTravelParser
from src.utils.browser import create_browser, create_context
from src.utils.antibot import delay_between_pages, delay_between_hotels, shuffle_items
from src.utils.notifications import notify_scrape_complete, notify_error

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logging.Formatter.converter = lambda *_: now_moscow().timetuple()
logger = logging.getLogger(__name__)

PARSERS = {
    "ostrovok": OstrovokParser,
    "hotel_site": HotelSiteParser,
    "ozon_travel": OzonTravelParser,
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


async def _scrape_source(
    browser,
    parser,
    hotel_config,
    hotel_id: int,
    source_config,
    checkin_dates,
    adults: int,
    base_date: date,
) -> tuple[int, int, int]:
    """Парсит источник через Playwright."""
    total = 0
    ok = 0
    fail = 0
    nights = 1

    context = await create_context(browser)
    try:
        for checkin in checkin_dates:
            checkout = checkin + timedelta(days=nights)
            total += 1

            page = await context.new_page()
            try:
                if source_config.has_dates:
                    url = build_url(source_config.url_template, checkin, checkout, nights, adults)
                else:
                    url = source_config.url_template

                result = await parser.scrape(
                    page, url, hotel_config.slug, checkin.isoformat()
                )

                with get_session() as session:
                    price_record = Price(
                        hotel_id=hotel_id,
                        source=source_config.name,
                        checkin_date=checkin,
                        checkin_offset_days=(checkin - base_date).days,
                        nights=nights,
                        price=result.price,
                        currency="RUB",
                        url=url,
                        raw_price_text=result.raw_text[:100] if result.raw_text else None,
                        error=result.error,
                    )
                    session.add(price_record)

                if result.price is not None:
                    ok += 1
                else:
                    fail += 1
            finally:
                await page.close()

            await delay_between_pages()
    finally:
        await context.close()

    return total, ok, fail


async def run_scraping(
    hotel_slug: Optional[str] = None,
    source_filter: Optional[str] = None,
    checkin_override: Optional[str] = None,
):
    """Основной цикл скрейпинга."""
    config = load_config()

    with get_session() as session:
        run = ScrapeRun(started_at=now_moscow())
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

    base_date = date.today()
    if checkin_override:
        checkin_dates = [date.fromisoformat(checkin_override)]
    else:
        checkin_dates = get_checkin_dates(config.schedule.checkin_offsets_days, base_date)

    adults = config.schedule.adults
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

                for sc in sources:
                    parser_class = PARSERS.get(sc.name)
                    if not parser_class:
                        logger.warning("Нет парсера для источника: %s", sc.name)
                        continue

                    parser = (
                        parser_class(widget=sc.widget)
                        if sc.name == "hotel_site"
                        else parser_class()
                    )

                    try:
                        proxy = getattr(parser, "proxy_url", None)
                        if proxy:
                            # Источник с прокси — отдельный браузер
                            async with create_browser(proxy_url=proxy) as proxy_browser:
                                t, s, f = await _scrape_source(
                                    proxy_browser, parser, hotel_config, hotel_id,
                                    sc, checkin_dates, adults, base_date,
                                )
                        else:
                            t, s, f = await _scrape_source(
                                browser, parser, hotel_config, hotel_id,
                                sc, checkin_dates, adults, base_date,
                            )
                        total_tasks += t
                        successful += s
                        failed += f
                    except Exception as e:
                        logger.error("Ошибка в источнике %s: %s", sc.name, e)
                        failed += 1
                        total_tasks += 1

                await delay_between_hotels()

        status = "completed"

    except Exception:
        status = "error"
        raise

    finally:
        with get_session() as session:
            run = session.get(ScrapeRun, run_id)
            if run:
                run.finished_at = now_moscow()
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
