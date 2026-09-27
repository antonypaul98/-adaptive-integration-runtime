-- Run only as a dedicated migration administrator. Runtime never owns schema/tables.
CREATE ROLE air_runtime NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
CREATE SCHEMA air_private;
REVOKE ALL ON SCHEMA air_private FROM PUBLIC;
CREATE TABLE air_private.tenant_logins (
    login NAME PRIMARY KEY,
    tenant_id UUID NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
REVOKE ALL ON air_private.tenant_logins FROM PUBLIC;

CREATE FUNCTION air.current_tenant() RETURNS UUID
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = pg_catalog, air_private AS $$
DECLARE requested UUID; authorized UUID;
BEGIN
    BEGIN
        requested := NULLIF(current_setting('air.tenant_id', true), '')::uuid;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid tenant context' USING ERRCODE = '42501';
    END;
    SELECT tenant_id INTO authorized FROM air_private.tenant_logins
        WHERE login = session_user AND enabled;
    IF requested IS NULL OR authorized IS NULL OR requested <> authorized THEN
        RAISE EXCEPTION 'unauthorized tenant context' USING ERRCODE = '42501';
    END IF;
    RETURN authorized;
END $$;
REVOKE ALL ON FUNCTION air.current_tenant() FROM PUBLIC;
GRANT USAGE ON SCHEMA air TO air_runtime;
GRANT EXECUTE ON FUNCTION air.current_tenant() TO air_runtime;

CREATE TABLE air.artifacts (
    tenant_id UUID NOT NULL DEFAULT air.current_tenant(),
    artifact_id UUID NOT NULL,
    kind TEXT NOT NULL CHECK (kind ~ '^[a-z][a-z0-9_]{0,63}$'),
    idempotency_key TEXT NOT NULL CHECK (length(idempotency_key) BETWEEN 1 AND 256),
    payload TEXT NOT NULL CHECK (octet_length(payload) <= 1048576
                                AND jsonb_typeof(payload::jsonb) = 'object'),
    content_hash TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, artifact_id),
    UNIQUE (tenant_id, kind, idempotency_key)
);
-- convert_to is STABLE, so compute in a protected insert trigger, not a generated column.
CREATE FUNCTION air.hash_artifact() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    NEW.content_hash := encode(sha256(convert_to(NEW.payload, 'UTF8')), 'hex');
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.hash_artifact() FROM PUBLIC;
CREATE TRIGGER artifact_hash BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.hash_artifact();

CREATE TABLE air.audit_events (
    tenant_id UUID NOT NULL,
    event_id UUID NOT NULL,
    artifact_id UUID NOT NULL,
    content_hash TEXT NOT NULL,
    action TEXT NOT NULL CHECK (action = 'artifact.created'),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, event_id),
    FOREIGN KEY (tenant_id, artifact_id) REFERENCES air.artifacts(tenant_id, artifact_id)
);
ALTER TABLE air.artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE air.artifacts FORCE ROW LEVEL SECURITY;
ALTER TABLE air.audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE air.audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY tenant_artifacts ON air.artifacts
    USING (tenant_id = air.current_tenant())
    WITH CHECK (tenant_id = air.current_tenant());
CREATE POLICY tenant_audit ON air.audit_events
    USING (tenant_id = air.current_tenant())
    WITH CHECK (tenant_id = air.current_tenant());

CREATE FUNCTION air.reject_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
    RAISE EXCEPTION 'AIR evidence is append-only' USING ERRCODE = '42501';
END $$;
REVOKE ALL ON FUNCTION air.reject_mutation() FROM PUBLIC;
CREATE TRIGGER immutable_artifacts BEFORE UPDATE OR DELETE OR TRUNCATE ON air.artifacts
    FOR EACH STATEMENT EXECUTE FUNCTION air.reject_mutation();
CREATE TRIGGER immutable_audit BEFORE UPDATE OR DELETE OR TRUNCATE ON air.audit_events
    FOR EACH STATEMENT EXECUTE FUNCTION air.reject_mutation();

CREATE FUNCTION air.record_artifact() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, air AS $$
BEGIN
    -- The definer can be an administrator: explicitly validate even if it bypasses RLS.
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized audit tenant' USING ERRCODE = '42501';
    END IF;
    INSERT INTO air.audit_events(tenant_id, event_id, artifact_id, content_hash, action)
    VALUES (NEW.tenant_id, NEW.artifact_id, NEW.artifact_id, NEW.content_hash, 'artifact.created');
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.record_artifact() FROM PUBLIC;
CREATE TRIGGER artifact_audit AFTER INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.record_artifact();
REVOKE ALL ON air.artifacts, air.audit_events FROM PUBLIC;
GRANT SELECT ON air.artifacts, air.audit_events TO air_runtime;
-- Callers cannot forge timestamps or the hash, and cannot insert audit records directly.
GRANT INSERT (tenant_id, artifact_id, kind, idempotency_key, payload)
    ON air.artifacts TO air_runtime;
