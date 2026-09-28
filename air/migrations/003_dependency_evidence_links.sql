-- Immutable dependency registries and impact records share the existing RLS/audit store.
CREATE FUNCTION air.validate_dependency_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE evidence JSONB; linked JSONB; registry JSONB; linked_hash TEXT; registry_hash TEXT;
BEGIN
    IF NEW.kind NOT IN ('contract_dependency_registry', 'contract_dependency_impact') THEN
        RETURN NEW;
    END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized dependency evidence' USING ERRCODE = '42501';
    END IF;
    evidence := NEW.payload::jsonb;
    BEGIN
        IF (evidence->>'tenant_id')::uuid IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'invalid dependency tenant' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'contract_dependency_registry' THEN
            SELECT payload::jsonb, content_hash INTO linked, linked_hash FROM air.artifacts
                WHERE tenant_id = NEW.tenant_id AND kind = 'contract_observation'
                AND artifact_id = (evidence#>>'{snapshot,artifact_id}')::uuid;
            IF linked IS NULL OR
               (evidence#>>'{snapshot,artifact_hash}') IS DISTINCT FROM linked_hash OR
               (evidence#>>'{snapshot,contract_hash}') IS DISTINCT FROM (linked->>'content_hash') THEN
                RAISE EXCEPTION 'invalid dependency snapshot link' USING ERRCODE = '23514';
            END IF;
        ELSE
            SELECT payload::jsonb, content_hash INTO linked, linked_hash FROM air.artifacts
                WHERE tenant_id = NEW.tenant_id AND kind = 'contract_change_set'
                AND artifact_id = (evidence#>>'{change_evidence,artifact_id}')::uuid;
            SELECT payload::jsonb, content_hash INTO registry, registry_hash FROM air.artifacts
                WHERE tenant_id = NEW.tenant_id AND kind = 'contract_dependency_registry'
                AND artifact_id = (evidence#>>'{registry,artifact_id}')::uuid;
            IF linked IS NULL OR registry IS NULL OR
               (evidence#>>'{change_evidence,artifact_hash}') IS DISTINCT FROM linked_hash OR
               (evidence#>>'{registry,artifact_hash}') IS DISTINCT FROM registry_hash OR
               (registry#>>'{snapshot,artifact_id}') IS DISTINCT FROM (linked#>>'{previous_snapshot,artifact_id}') OR
               (registry#>>'{snapshot,artifact_hash}') IS DISTINCT FROM (linked#>>'{previous_snapshot,artifact_hash}') THEN
                RAISE EXCEPTION 'invalid dependency impact links' USING ERRCODE = '23514';
            END IF;
        END IF;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid dependency identity' USING ERRCODE = '23514';
    END;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.validate_dependency_links() FROM PUBLIC;
CREATE TRIGGER dependency_evidence_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_dependency_links();
