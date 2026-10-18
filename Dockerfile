# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS build
WORKDIR /src
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir --prefix=/install ".[gcp]"

FROM python:3.12-slim
RUN useradd --system --uid 10001 --no-create-home app
WORKDIR /app
COPY --from=build /install /usr/local
COPY skills ./skills
COPY config ./config
COPY migrations ./migrations
ENV AURANEXUS_HOME=/app \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080
USER 10001
EXPOSE 8080
CMD ["python", "-m", "auranexus"]
