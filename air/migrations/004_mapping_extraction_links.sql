-- Extend immutable evidence, RLS and audit with mapping/extraction link validation.
CREATE FUNCTION air.validate_mapping_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE evidence JSONB; snapshot JSONB; snapshot_hash TEXT; registry JSONB;
        linked JSONB; linked_hash TEXT; reference JSONB; provenance JSONB;
        snapshot_id UUID;
BEGIN
    IF NEW.kind NOT IN ('registered_adapter_mapping', 'adapter_dependency_extraction') THEN
        RETURN NEW;
    END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized mapping evidence' USING ERRCODE = '42501';
    END IF;
    evidence := NEW.payload::jsonb;
    BEGIN
        IF (evidence->>'tenant_id')::uuid IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'invalid mapping tenant' USING ERRCODE = '23514';
        END IF;
        snapshot_id := (evidence#>>'{snapshot,artifact_id}')::uuid;
        SELECT payload::jsonb, content_hash INTO snapshot, snapshot_hash FROM air.artifacts
            WHERE tenant_id = NEW.tenant_id AND artifact_id = snapshot_id
            AND kind = 'contract_observation';
        IF snapshot IS NULL OR
           (evidence#>>'{snapshot,artifact_hash}') IS DISTINCT FROM snapshot_hash OR
           (evidence#>>'{snapshot,contract_hash}') IS DISTINCT FROM (snapshot->>'content_hash') THEN
            RAISE EXCEPTION 'invalid mapping snapshot link' USING ERRCODE = '23514';
        END IF;
        IF NEW.kind = 'registered_adapter_mapping' THEN
            IF (evidence#>>'{manifest,tenant_id}')::uuid IS DISTINCT FROM NEW.tenant_id OR
               (evidence#>>'{manifest,snapshot_id}')::uuid IS DISTINCT FROM snapshot_id THEN
                RAISE EXCEPTION 'invalid mapping ownership' USING ERRCODE = '23514';
            END IF;
        ELSE
            SELECT payload::jsonb, content_hash INTO registry, linked_hash FROM air.artifacts
                WHERE tenant_id = NEW.tenant_id AND kind = 'contract_dependency_registry'
                AND artifact_id = (evidence#>>'{registry,artifact_id}')::uuid;
            IF registry IS NULL OR
               (evidence#>>'{registry,artifact_hash}') IS DISTINCT FROM linked_hash OR
               (registry#>>'{snapshot,artifact_id}')::uuid IS DISTINCT FROM snapshot_id THEN
                RAISE EXCEPTION 'invalid extraction registry link' USING ERRCODE = '23514';
            END IF;
            IF jsonb_typeof(evidence->'mappings') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'invalid extraction mapping list' USING ERRCODE = '23514';
            END IF;
            IF jsonb_array_length(evidence->'mappings') NOT BETWEEN 1 AND 32 THEN
                RAISE EXCEPTION 'invalid extraction mapping count' USING ERRCODE = '23514';
            END IF;
            FOR reference IN SELECT value FROM jsonb_array_elements(evidence->'mappings') LOOP
                SELECT payload::jsonb, content_hash INTO linked, linked_hash FROM air.artifacts
                    WHERE tenant_id = NEW.tenant_id AND kind = 'registered_adapter_mapping'
                    AND artifact_id = (reference->>'artifact_id')::uuid;
                IF linked IS NULL OR (reference->>'artifact_hash') IS DISTINCT FROM linked_hash OR
                   (linked#>>'{snapshot,artifact_id}')::uuid IS DISTINCT FROM snapshot_id THEN
                    RAISE EXCEPTION 'invalid registered mapping link' USING ERRCODE = '23514';
                END IF;
            END LOOP;
            IF NOT (evidence ? 'explicit_registry') THEN
                RAISE EXCEPTION 'missing extraction base' USING ERRCODE = '23514';
            END IF;
            IF evidence->'explicit_registry' <> 'null'::jsonb THEN
                SELECT payload::jsonb, content_hash INTO linked, linked_hash FROM air.artifacts
                    WHERE tenant_id = NEW.tenant_id AND kind = 'contract_dependency_registry'
                    AND artifact_id = (evidence#>>'{explicit_registry,artifact_id}')::uuid;
                IF linked IS NULL OR
                   (evidence#>>'{explicit_registry,artifact_hash}') IS DISTINCT FROM linked_hash OR
                   (linked#>>'{snapshot,artifact_id}')::uuid IS DISTINCT FROM snapshot_id THEN
                    RAISE EXCEPTION 'invalid explicit registry link' USING ERRCODE = '23514';
                END IF;
            END IF;
            IF jsonb_typeof(evidence->'provenance') IS DISTINCT FROM 'array' THEN
                RAISE EXCEPTION 'invalid extraction provenance' USING ERRCODE = '23514';
            END IF;
            FOR provenance IN SELECT value FROM jsonb_array_elements(evidence->'provenance') LOOP
                IF NOT EXISTS (SELECT 1 FROM jsonb_array_elements(evidence->'mappings') AS m
                               WHERE m.value = provenance->'mapping_artifact') THEN
                    RAISE EXCEPTION 'unlinked mapping provenance' USING ERRCODE = '23514';
                END IF;
            END LOOP;
        END IF;
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid mapping identity' USING ERRCODE = '23514';
    END;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.validate_mapping_links() FROM PUBLIC;
CREATE TRIGGER mapping_evidence_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_mapping_links();
