"""Persistence abstraction. Records are tenant-scoped JSON documents addressed by collection.

Collections: projects, events, proposals, checkpoints, register (approved artifacts),
reports (informational agent output), agent_runs, members, notifications.
"""

from __future__ import annotations

import copy
import threading
from collections.abc import Callable
from typing import Any, Protocol

Doc = dict[str, Any]


class Store(Protocol):
    def put(self, collection: str, tenant_id: str, id: str, data: Doc, project_id: str | None = None) -> None: ...

    def put_if(
        self,
        collection: str,
        tenant_id: str,
        id: str,
        data: Doc,
        expect: dict[str, Any],
        project_id: str | None = None,
    ) -> bool:
        """Compare-and-set: write only if the stored doc currently matches every key in ``expect``."""
        ...

    def get(self, collection: str, tenant_id: str, id: str) -> Doc | None: ...

    def list(
        self,
        collection: str,
        tenant_id: str,
        project_id: str | None = None,
        filters: dict[str, Any] | None = None,
        limit: int = 5000,
    ) -> list[Doc]: ...

    def append_audit(self, tenant_id: str, build: Callable[[Doc | None], Doc]) -> Doc:
        """Atomically build and append the next hash-chained audit entry."""
        ...

    def list_audit(self, tenant_id: str, project_id: str | None = None, limit: int = 1000) -> list[Doc]: ...

    def ping(self) -> bool: ...


class MemoryStore:
    """In-process store for local development and tests."""

    def __init__(self) -> None:
        self._docs: dict[tuple[str, str, str], tuple[str | None, Doc]] = {}
        self._audit: dict[str, list[Doc]] = {}
        self._lock = threading.RLock()

    def put(self, collection, tenant_id, id, data, project_id=None):
        with self._lock:
            self._docs[(tenant_id, collection, id)] = (project_id, copy.deepcopy(data))

    def put_if(self, collection, tenant_id, id, data, expect, project_id=None):
        with self._lock:
            cur = self._docs.get((tenant_id, collection, id))
            if cur is None or any(str(cur[1].get(k)) != str(v) for k, v in expect.items()):
                return False
            self._docs[(tenant_id, collection, id)] = (project_id, copy.deepcopy(data))
            return True

    def get(self, collection, tenant_id, id):
        with self._lock:
            cur = self._docs.get((tenant_id, collection, id))
            return copy.deepcopy(cur[1]) if cur else None

    def list(self, collection, tenant_id, project_id=None, filters=None, limit=5000):
        with self._lock:
            out = []
            for (t, c, _), (pid, doc) in self._docs.items():
                if t != tenant_id or c != collection:
                    continue
                if project_id is not None and pid != project_id:
                    continue
                if filters and any(str(doc.get(k)) != str(v) for k, v in filters.items()):
                    continue
                out.append(copy.deepcopy(doc))
                if len(out) >= limit:
                    break
            return out

    def append_audit(self, tenant_id, build):
        with self._lock:
            chain = self._audit.setdefault(tenant_id, [])
            entry = build(chain[-1] if chain else None)
            chain.append(entry)
            return copy.deepcopy(entry)

    def list_audit(self, tenant_id, project_id=None, limit=1000):
        with self._lock:
            chain = self._audit.get(tenant_id, [])
            rows = [e for e in chain if project_id is None or e.get("project_id") == project_id]
            return [copy.deepcopy(e) for e in rows[-limit:]]

    def ping(self) -> bool:
        return True
