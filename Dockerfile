# syntax=docker/dockerfile:1

FROM python:3.11-alpine AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apk add --no-cache \
    build-base \
    linux-headers \
    curl \
    libffi-dev \
    openssl-dev \
    openjpeg-dev \
    jpeg-dev \
    zlib-dev \
    freetype-dev \
    harfbuzz-dev \
    tiff-dev \
    openblas-dev \
    gfortran

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

COPY . .

RUN chmod +x /app/scripts/docker-entrypoint.sh

ENV LORI_HOME=/data/lori \
    ASSISTANT_ROOT=/data/lori/workspace \
    OLLAMA_BASE_URL=http://ollama:11434 \
    PYTHONPATH=/app

RUN mkdir -p /data/lori/workspace /data/lori/uploads /data/lori/cache

EXPOSE 8001

ENTRYPOINT ["/app/scripts/docker-entrypoint.sh"]
