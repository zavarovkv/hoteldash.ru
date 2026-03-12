"""Telegram-уведомления (опционально)."""

import os
import logging
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)


def send_telegram_message(text: str) -> bool:
    """Отправляет сообщение в Telegram. Возвращает True при успехе."""
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.debug("Telegram не настроен, пропускаем уведомление")
        return False

    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }).encode("utf-8")

        req = urllib.request.Request(url, data=data)
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if result.get("ok"):
                logger.info("Telegram-уведомление отправлено")
                return True
            logger.warning("Telegram API вернул ошибку: %s", result)
            return False
    except Exception as e:
        logger.error("Ошибка отправки Telegram-уведомления: %s", e)
        return False


def notify_scrape_complete(successful: int, failed: int, total: int):
    """Уведомление о завершении скрейпинга."""
    status = "✅" if failed == 0 else "⚠️"
    text = (
        f"{status} <b>HotelDash — скрейпинг завершён</b>\n"
        f"Успешно: {successful}/{total}\n"
        f"Ошибок: {failed}/{total}"
    )
    send_telegram_message(text)


def notify_error(error: str):
    """Уведомление о критической ошибке."""
    text = f"🚨 <b>HotelDash — ошибка</b>\n<pre>{error[:500]}</pre>"
    send_telegram_message(text)
