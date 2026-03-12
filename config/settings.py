"""Настройки парсера: таймауты, задержки, ретраи."""

# Задержки между запросами (секунды)
DELAY_BETWEEN_PAGES_MIN = 3
DELAY_BETWEEN_PAGES_MAX = 8
DELAY_BETWEEN_HOTELS_MIN = 10
DELAY_BETWEEN_HOTELS_MAX = 20

# Таймауты Playwright (миллисекунды)
PAGE_LOAD_TIMEOUT = 30_000
ELEMENT_WAIT_TIMEOUT = 15_000

# Ретраи
MAX_RETRIES = 2
RETRY_DELAY = 5  # секунд

# Браузер
VIEWPORT_WIDTH = 1920
VIEWPORT_HEIGHT = 1080
LOCALE = "ru-RU"
TIMEZONE = "Europe/Moscow"

# Скриншоты при ошибках
SCREENSHOTS_DIR = "screenshots"
SAVE_SCREENSHOTS_ON_ERROR = True
