-- AuraNexus schema. Apply as the DB owner. The application connects as a member of role
-- auranexus_app (no BYPASSRLS, not the table owner) so row-level security is always enforced.

CREATE TABLE IF NOT EXISTS records (
    created_seq  BIGSERIAL,
    tenant_id    TEXT        NOT NULL,
    collection   TEXT        NOT NULL,
    id           TEXT        NOT NULL,
    project_id   TEXT,
    data         JSONB       NOT NULL,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, collection, id)
);
CREATE INDEX IF NOT EXISTS records_project_idx ON records (tenant_id, collection, project_id);
CREATE INDEX IF NOT EXISTS records_status_idx  ON records (tenant_id, collection, (data->>'status'));

CREATE TABLE IF NOT EXISTS audit_log (
    tenant_id  TEXT        NOT NULL,
    seq        BIGINT      NOT NULL,
    project_id TEXT,
    entry      JSONB       NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (tenant_id, seq)
);
CREATE INDEX IF NOT EXISTS audit_project_idx ON audit_log (tenant_id, project_id);

-- The audit log is append-only.
CREATE OR REPLACE FUNCTION audit_log_immutable() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_update ON audit_log;
CREATE TRIGGER audit_log_no_update BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION audit_log_immutable();

-- Row-level security: a transaction only sees rows for app.tenant_id.
ALTER TABLE records   ENABLE ROW LEVEL SECURITY;
ALTER TABLE records   FORCE  ROW LEVEL SECURITY;
ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON records;
CREATE POLICY tenant_isolation ON records
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON audit_log;
CREATE POLICY tenant_isolation ON audit_log
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auranexus_app') THEN
        CREATE ROLE auranexus_app NOLOGIN;
    END IF;
END $$;
-- Cloud SQL owners are not superusers and cannot ALTER those attributes, so verify instead: the app role must be
-- unable to bypass row-level security, otherwise tenant isolation would be void.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'auranexus_app' AND (rolsuper OR rolbypassrls)) THEN
        RAISE EXCEPTION 'role auranexus_app must be NOSUPERUSER NOBYPASSRLS';
    END IF;
END $$;
GRANT SELECT, INSERT, UPDATE ON records TO auranexus_app;
GRANT SELECT, INSERT ON audit_log TO auranexus_app;
GRANT USAGE ON SEQUENCE records_created_seq_seq TO auranexus_app;
