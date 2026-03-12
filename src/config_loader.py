"""Загрузка конфигурации отелей из hotels.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Optional, List

import yaml


@dataclass
class SourceConfig:
    name: str
    url_template: str
    has_dates: bool = True


@dataclass
class HotelConfig:
    slug: str
    name: str
    city: str
    stars: Optional[int]
    sources: List[SourceConfig] = field(default_factory=list)


@dataclass
class ScheduleConfig:
    checkin_offsets_days: List[int]
    nights: int
    adults: int


@dataclass
class AppConfig:
    hotels: List[HotelConfig]
    schedule: ScheduleConfig


def load_config(config_path: Optional[str] = None) -> AppConfig:
    """Загружает конфигурацию из YAML-файла."""
    if config_path is None:
        config_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config", "hotels.yaml"
        )

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    hotels = []
    for h in raw["hotels"]:
        sources = []
        for source_name, source_data in h.get("sources", {}).items():
            sources.append(
                SourceConfig(
                    name=source_name,
                    url_template=source_data["url_template"],
                    has_dates=source_data.get("has_dates", True),
                )
            )
        hotels.append(
            HotelConfig(
                slug=h["slug"],
                name=h["name"],
                city=h["city"],
                stars=h.get("stars"),
                sources=sources,
            )
        )

    schedule_raw = raw.get("schedule", {})
    schedule = ScheduleConfig(
        checkin_offsets_days=schedule_raw.get("checkin_offsets_days", [1, 3, 7, 14, 30]),
        nights=schedule_raw.get("nights", 1),
        adults=schedule_raw.get("adults", 2),
    )

    return AppConfig(hotels=hotels, schedule=schedule)


def build_url(template: str, checkin: date, checkout: date, nights: int = 1, adults: int = 2) -> str:
    """Подставляет даты и параметры в URL-шаблон."""
    return template.format(
        checkin=checkin.isoformat(),
        checkout=checkout.isoformat(),
        checkin_dot=checkin.strftime("%d.%m.%Y"),
        checkout_dot=checkout.strftime("%d.%m.%Y"),
        nights=nights,
        adults=adults,
    )


def get_checkin_dates(offsets: List[int], base_date: Optional[date] = None) -> List[date]:
    """Генерирует даты заезда на основе смещений от базовой даты."""
    if base_date is None:
        base_date = date.today()
    return [base_date + timedelta(days=offset) for offset in offsets]
