"""Тесты парсеров — проверка parse_price_text и базовой логики."""

import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.parsers.base import BaseParser, ParseResult
from src.config_loader import load_config, build_url, get_checkin_dates
from datetime import date


class TestParsePriceText(unittest.TestCase):
    """Тесты конвертации текста цены в число."""

    def test_basic_price(self):
        self.assertEqual(BaseParser.parse_price_text("12500"), 12500)

    def test_price_with_spaces(self):
        self.assertEqual(BaseParser.parse_price_text("12 500"), 12500)

    def test_price_with_ruble_sign(self):
        self.assertEqual(BaseParser.parse_price_text("12 500 ₽"), 12500)

    def test_price_with_rub(self):
        self.assertEqual(BaseParser.parse_price_text("12 500 руб."), 12500)

    def test_price_with_from(self):
        self.assertEqual(BaseParser.parse_price_text("от 8 900 ₽"), 8900)

    def test_empty_string(self):
        self.assertIsNone(BaseParser.parse_price_text(""))

    def test_none(self):
        self.assertIsNone(BaseParser.parse_price_text(None))

    def test_no_digits(self):
        self.assertIsNone(BaseParser.parse_price_text("нет цены"))

    def test_too_small(self):
        self.assertIsNone(BaseParser.parse_price_text("50"))

    def test_too_large(self):
        self.assertIsNone(BaseParser.parse_price_text("99999999999"))

    def test_nbsp_spaces(self):
        self.assertEqual(BaseParser.parse_price_text("12\u00a0500\u00a0₽"), 12500)


class TestConfigLoader(unittest.TestCase):
    """Тесты загрузки конфигурации."""

    def test_load_config(self):
        config = load_config()
        self.assertGreater(len(config.hotels), 0)
        self.assertGreater(len(config.schedule.checkin_offsets_days), 0)

    def test_hotel_has_sources(self):
        config = load_config()
        hotel = config.hotels[0]
        self.assertGreater(len(hotel.sources), 0)

    def test_build_url(self):
        template = "https://example.com/?checkin={checkin}&checkout={checkout}"
        url = build_url(template, date(2026, 3, 20), date(2026, 3, 21))
        self.assertEqual(url, "https://example.com/?checkin=2026-03-20&checkout=2026-03-21")

    def test_build_url_dot_format(self):
        template = "https://example.com/?dates={checkin_dot}-{checkout_dot}"
        url = build_url(template, date(2026, 3, 20), date(2026, 3, 21))
        self.assertEqual(url, "https://example.com/?dates=20.03.2026-21.03.2026")

    def test_get_checkin_dates(self):
        base = date(2026, 3, 13)
        dates = get_checkin_dates([1, 7], base)
        self.assertEqual(dates, [date(2026, 3, 14), date(2026, 3, 20)])


if __name__ == "__main__":
    unittest.main()
