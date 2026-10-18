"""Apply migrations/*.sql in order, once each, then seed declared tenants/admins.

Runs as the Cloud Run job ``auranexus-migrate-<env>`` with the database OWNER url
(AURANEXUS_MIGRATION_DATABASE_URL); the app itself never owns tables, so row-level security cannot be
bypassed by application code.

Tenant bootstrap: AURANEXUS_BOOTSTRAP_TENANTS='{"acme": "pm@acme.com"}' (from Terraform ``tenants[*].admin_email``)
registers each tenant and makes that person its admin + PM. Idempotent; never removes anyone.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any


def bootstrap_rows(spec: dict[str, str]) -> list[tuple[str, str, str, dict[str, Any]]]:
    """(tenant_scope, collection, id, data) rows for the given {tenant: admin_email} mapping."""
    rows: list[tuple[str, str, str, dict[str, Any]]] = []
    for tenant, email in spec.items():
        rows.append(("_system", "tenants", tenant, {"id": tenant, "name": tenant}))
        if email:
            rows.append((tenant, "members", email.lower(), {"email": email.lower(), "roles": ["admin", "pm"]}))
    return rows


def main() -> int:
    import psycopg
    from psycopg.types.json import Jsonb

    url = os.environ.get("AURANEXUS_MIGRATION_DATABASE_URL") or os.environ.get("AURANEXUS_DATABASE_URL")
    if not url:
        print("AURANEXUS_MIGRATION_DATABASE_URL is required", file=sys.stderr)
        return 2
    url = url.replace("postgresql+psycopg://", "postgresql://")
    home = Path(os.environ.get("AURANEXUS_HOME", Path(__file__).resolve().parents[2]))
    files = sorted((home / "migrations").glob("*.sql"))
    bootstrap = json.loads(os.environ.get("AURANEXUS_BOOTSTRAP_TENANTS", "{}") or "{}")

    with psycopg.connect(url, autocommit=False) as conn:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {r[0] for r in conn.execute("SELECT name FROM schema_migrations")}
        for f in files:
            if f.name in done:
                continue
            print(f"applying {f.name}")
            conn.execute(f.read_text(encoding="utf-8"))
            conn.execute("INSERT INTO schema_migrations (name) VALUES (%s)", (f.name,))
            conn.commit()

        for scope, collection, rid, data in bootstrap_rows(bootstrap):
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (scope,))  # RLS applies to the owner too
            conn.execute(
                "INSERT INTO records (tenant_id, collection, id, data) VALUES (%s, %s, %s, %s) "
                "ON CONFLICT (tenant_id, collection, id) DO UPDATE SET data = EXCLUDED.data, updated_at = now()",
                (scope, collection, rid, Jsonb(data)),
            )
            print(f"bootstrapped {collection}/{rid} in {scope}")
            conn.commit()
    print("migrations up to date")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
