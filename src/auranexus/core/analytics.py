"""Analytics sink feeding BigQuery (PM dashboards, HITL latency, quality scoring). Never blocks the workflow."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from ..config import Settings

log = logging.getLogger("auranexus.analytics")


class AnalyticsSink(Protocol):
    def emit(self, table: str, row: dict[str, Any]) -> None: ...


class NullSink:
    def __init__(self) -> None:
        self.rows: list[tuple[str, dict[str, Any]]] = []  # inspectable in tests

    def emit(self, table: str, row: dict[str, Any]) -> None:
        self.rows.append((table, row))


class BigQuerySink:
    def __init__(self, settings: Settings) -> None:
        from google.cloud import bigquery

        self._client = bigquery.Client(project=settings.gcp_project)
        self._dataset = f"{settings.gcp_project}.{settings.bigquery_dataset}"

    def emit(self, table: str, row: dict[str, Any]) -> None:
        try:
            errors = self._client.insert_rows_json(f"{self._dataset}.{table}", [row])
            if errors:
                log.warning("bigquery insert errors for %s: %s", table, errors)
        except Exception:  # analytics must never fail a business transaction
            log.exception("bigquery emit failed for %s", table)


def build_sink(settings: Settings) -> AnalyticsSink:
    return BigQuerySink(settings) if settings.analytics_backend == "bigquery" else NullSink()
