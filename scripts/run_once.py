"""Ручной запуск для тестирования отдельных парсеров."""

import sys
import os
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.main import run_scraping


def main():
    parser = argparse.ArgumentParser(description="Запуск парсера для одного отеля/источника")
    parser.add_argument("--hotel", required=True, help="Slug отеля (например, metropol-moscow)")
    parser.add_argument("--source", required=True, help="Источник (ostrovok, tbank, onetwotrip, yandex_travel, avito)")
    parser.add_argument("--checkin", required=True, help="Дата заезда (YYYY-MM-DD)")
    args = parser.parse_args()

    print(f"Запуск парсера: отель={args.hotel}, источник={args.source}, дата={args.checkin}")

    asyncio.run(run_scraping(
        hotel_slug=args.hotel,
        source_filter=args.source,
        checkin_override=args.checkin,
    ))


if __name__ == "__main__":
    main()
