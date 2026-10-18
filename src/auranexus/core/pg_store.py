"""PostgreSQL store (Cloud SQL). Tenant isolation: tenant_id column + row-level security.

Every transaction sets ``app.tenant_id``; the policies in migrations/001_init.sql only expose rows
for that tenant, so a bug in application code cannot leak data across tenants.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine

from .store import Doc

_KEY = re.compile(r"^[a-z_][a-z0-9_]*$")


class PostgresStore:
    def __init__(self, url: str, pool_size: int = 5) -> None:
        self.engine: Engine = create_engine(url, pool_size=pool_size, pool_pre_ping=True, future=True)

    @staticmethod
    def _scope(conn: Connection, tenant_id: str) -> None:
        conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": tenant_id})

    def put(self, collection, tenant_id, id, data, project_id=None):
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            conn.execute(
                text(
                    """INSERT INTO records (tenant_id, collection, id, project_id, data)
                       VALUES (:t, :c, :i, :p, CAST(:d AS jsonb))
                       ON CONFLICT (tenant_id, collection, id)
                       DO UPDATE SET data = EXCLUDED.data, project_id = EXCLUDED.project_id, updated_at = now()"""
                ),
                {"t": tenant_id, "c": collection, "i": id, "p": project_id, "d": json.dumps(data, default=str)},
            )

    def put_if(self, collection, tenant_id, id, data, expect, project_id=None):
        params: dict[str, Any] = {
            "t": tenant_id,
            "c": collection,
            "i": id,
            "p": project_id,
            "d": json.dumps(data, default=str),
        }
        clauses = ""
        for n, (k, v) in enumerate(expect.items()):
            if not _KEY.match(k):
                raise ValueError(f"bad key {k}")
            clauses += f" AND data->>'{k}' = :e{n}"
            params[f"e{n}"] = str(v)
        sql = (
            "UPDATE records SET data = CAST(:d AS jsonb), project_id = :p, updated_at = now() "
            "WHERE tenant_id = :t AND collection = :c AND id = :i" + clauses
        )
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            return conn.execute(text(sql), params).rowcount == 1

    def get(self, collection, tenant_id, id):
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            row = conn.execute(
                text("SELECT data FROM records WHERE tenant_id=:t AND collection=:c AND id=:i"),
                {"t": tenant_id, "c": collection, "i": id},
            ).first()
            return row[0] if row else None

    def list(self, collection, tenant_id, project_id=None, filters=None, limit=5000):
        sql = "SELECT data FROM records WHERE tenant_id=:t AND collection=:c"
        params: dict[str, Any] = {"t": tenant_id, "c": collection, "lim": limit}
        if project_id is not None:
            sql += " AND project_id=:p"
            params["p"] = project_id
        for n, (k, v) in enumerate((filters or {}).items()):
            if not _KEY.match(k):
                raise ValueError(f"bad filter key {k}")
            sql += f" AND data->>'{k}' = :f{n}"
            params[f"f{n}"] = str(v)
        sql += " ORDER BY created_seq LIMIT :lim"
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            return [r[0] for r in conn.execute(text(sql), params)]

    def append_audit(self, tenant_id, build: Callable[[Doc | None], Doc]) -> Doc:
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:t))"), {"t": tenant_id})
            row = conn.execute(
                text("SELECT entry FROM audit_log WHERE tenant_id=:t ORDER BY seq DESC LIMIT 1"), {"t": tenant_id}
            ).first()
            entry = build(row[0] if row else None)
            conn.execute(
                text(
                    "INSERT INTO audit_log (tenant_id, seq, project_id, entry) "
                    "VALUES (:t, :s, :p, CAST(:e AS jsonb))"
                ),
                {"t": tenant_id, "s": entry["seq"], "p": entry.get("project_id"), "e": json.dumps(entry, default=str)},
            )
            return entry

    def list_audit(self, tenant_id, project_id=None, limit=1000):
        sql = "SELECT entry FROM audit_log WHERE tenant_id=:t"
        params: dict[str, Any] = {"t": tenant_id, "lim": limit}
        if project_id:
            sql += " AND project_id=:p"
            params["p"] = project_id
        sql += " ORDER BY seq DESC LIMIT :lim"
        with self.engine.begin() as conn:
            self._scope(conn, tenant_id)
            return list(reversed([r[0] for r in conn.execute(text(sql), params)]))

    def ping(self) -> bool:
        with self.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
