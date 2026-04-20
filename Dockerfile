FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md alembic.ini ./
COPY src ./src
COPY alembic ./alembic
RUN uv sync --frozen --no-dev

CMD ["uv", "run", "python", "-m", "multimedia_bot"]
