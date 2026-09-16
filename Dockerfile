FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    IN_DOCKER=1

WORKDIR /app

# system deps for psycopg / scientific stack
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev git curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# default: keep the container alive so `docker compose run` can exec agent tasks
CMD ["bash", "-lc", "python -c 'from fdp.db import wait_ready; print(\"pg ready\", wait_ready())' && tail -f /dev/null"]
