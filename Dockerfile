FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md requirements-dev.txt ./
COPY src ./src
COPY tests ./tests
COPY scripts ./scripts
COPY migrations ./migrations

RUN python -m pip install --no-cache-dir -r requirements-dev.txt

CMD ["python", "-m", "pytest"]
