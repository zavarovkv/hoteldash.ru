FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Системные зависимости для Playwright Chromium + Camoufox Firefox
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 \
    libxdamage1 libxfixes3 libxrandr2 libgbm1 \
    libpango-1.0-0 libcairo2 libasound2 libatspi2.0-0 \
    libgtk-3-0 libdbus-glib-1-2 libxt6 \
    && rm -rf /var/lib/apt/lists/*

# Зависимости Python (кэшируются отдельным слоем)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    playwright install chromium && \
    python -m camoufox fetch

# Код приложения
COPY config/ config/
COPY src/ src/
COPY scripts/ scripts/

CMD ["python", "-m", "src.main"]
