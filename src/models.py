"""SQLAlchemy модели для HotelDash."""

from datetime import datetime

from sqlalchemy import (
    Column,
    Integer,
    String,
    SmallInteger,
    Date,
    DateTime,
    ForeignKey,
    Index,
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Hotel(Base):
    __tablename__ = "hotels"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False)
    city = Column(String(100), nullable=False)
    stars = Column(SmallInteger)
    slug = Column(String(100), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    prices = relationship("Price", back_populates="hotel")


class Price(Base):
    __tablename__ = "prices"

    id = Column(Integer, primary_key=True)
    hotel_id = Column(Integer, ForeignKey("hotels.id"), nullable=False)
    source = Column(String(50), nullable=False)
    checkin_date = Column(Date, nullable=False)
    nights = Column(Integer, nullable=False, default=1)
    price = Column(Integer)
    currency = Column(String(3), default="RUB")
    scraped_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    raw_price_text = Column(String(100))
    error = Column(String(500))

    hotel = relationship("Hotel", back_populates="prices")

    __table_args__ = (
        Index("idx_prices_hotel_source_checkin", "hotel_id", "source", "checkin_date"),
        Index("idx_prices_scraped_at", "scraped_at"),
    )


class ScrapeRun(Base):
    __tablename__ = "scrape_runs"

    id = Column(Integer, primary_key=True)
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    finished_at = Column(DateTime)
    total_tasks = Column(Integer, default=0)
    successful = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String(20), default="running")
