# syntax=docker/dockerfile:1
FROM python:3.9-slim-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10002 backup

WORKDIR /app

COPY docker/backup/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm /tmp/requirements.txt

COPY src/config.py /app/src/config.py
COPY src/backup/ /app/src/backup/

USER backup
ENV PYTHONPATH=/app

CMD ["python", "-m", "src.backup", "loop"]
