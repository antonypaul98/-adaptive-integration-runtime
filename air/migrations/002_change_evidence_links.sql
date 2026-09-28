-- Keep immutable artifacts and audit semantics; add database validation of snapshot links.
CREATE FUNCTION air.validate_change_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE evidence JSONB; prior JSONB; current_doc JSONB; prior_hash TEXT; current_hash TEXT;
BEGIN
    IF NEW.kind <> 'contract_change_set' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized change evidence' USING ERRCODE = '42501';
    END IF;
    evidence := NEW.payload::jsonb;
    BEGIN
        IF (evidence->>'tenant_id')::uuid IS DISTINCT FROM NEW.tenant_id THEN
            RAISE EXCEPTION 'invalid change tenant' USING ERRCODE = '23514';
        END IF;
        SELECT payload::jsonb, content_hash INTO prior, prior_hash FROM air.artifacts
            WHERE tenant_id = NEW.tenant_id
            AND artifact_id = (evidence#>>'{previous_snapshot,artifact_id}')::uuid
            AND kind = 'contract_observation';
        SELECT payload::jsonb, content_hash INTO current_doc, current_hash FROM air.artifacts
            WHERE tenant_id = NEW.tenant_id
            AND artifact_id = (evidence#>>'{new_snapshot,artifact_id}')::uuid
            AND kind = 'contract_observation';
    EXCEPTION WHEN invalid_text_representation THEN
        RAISE EXCEPTION 'invalid snapshot identity' USING ERRCODE = '23514';
    END;
    IF prior IS NULL OR current_doc IS NULL OR
       (evidence#>>'{previous_snapshot,artifact_hash}') IS DISTINCT FROM prior_hash OR
       (evidence#>>'{new_snapshot,artifact_hash}') IS DISTINCT FROM current_hash OR
       (evidence#>>'{previous_snapshot,contract_hash}') IS DISTINCT FROM (prior->>'content_hash') OR
       (evidence#>>'{new_snapshot,contract_hash}') IS DISTINCT FROM (current_doc->>'content_hash') OR
       (prior->>'source_id') IS NULL OR (prior->>'origin') IS NULL OR
       (prior->>'normalization') IS NULL OR
       (prior->>'source_id') IS DISTINCT FROM (current_doc->>'source_id') OR
       (prior->>'origin') IS DISTINCT FROM (current_doc->>'origin') OR
       (prior->>'normalization') IS DISTINCT FROM (current_doc->>'normalization') THEN
        RAISE EXCEPTION 'invalid or unauthorized snapshot linkage' USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.validate_change_links() FROM PUBLIC;
CREATE TRIGGER change_evidence_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_change_links();
