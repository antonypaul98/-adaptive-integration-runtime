-- Downstream edges extend the existing registry; endpoints resolve ONLY inside it.
CREATE FUNCTION air.validate_workflow_edges() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE evidence JSONB; edge JSONB; endpoint JSONB; version TEXT;
BEGIN
    IF NEW.kind <> 'contract_dependency_registry' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized workflow registry' USING ERRCODE = '42501';
    END IF;
    evidence := NEW.payload::jsonb;
    version := evidence->>'registry_version';
    IF NOT (evidence ? 'workflow_edges') THEN
        IF version = 'air-dependency-impact-v2' THEN
            RAISE EXCEPTION 'missing workflow edges' USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;
    IF version IS DISTINCT FROM 'air-dependency-impact-v2' OR
       jsonb_typeof(evidence->'workflow_edges') IS DISTINCT FROM 'array' OR
       jsonb_typeof(evidence->'dependencies') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'invalid workflow registry' USING ERRCODE = '23514';
    END IF;
    IF jsonb_array_length(evidence->'workflow_edges') NOT BETWEEN 1 AND 2000 OR
       jsonb_array_length(evidence->'dependencies') NOT BETWEEN 1 AND 1000 THEN
        RAISE EXCEPTION 'workflow registry limit' USING ERRCODE = '23514';
    END IF;
    FOR edge IN SELECT value FROM jsonb_array_elements(evidence->'workflow_edges') LOOP
        IF jsonb_typeof(edge) IS DISTINCT FROM 'object' THEN
            RAISE EXCEPTION 'invalid workflow edge' USING ERRCODE = '23514';
        END IF;
        IF NOT (edge ?& ARRAY['upstream', 'downstream', 'relation']) OR
           edge - ARRAY['upstream', 'downstream', 'relation'] <> '{}'::jsonb OR
           edge->>'relation' IS DISTINCT FROM 'consumes_output' THEN
            RAISE EXCEPTION 'invalid workflow edge' USING ERRCODE = '23514';
        END IF;
        FOR endpoint IN SELECT edge->'upstream' UNION ALL SELECT edge->'downstream' LOOP
            -- No tenant overrides, external registry references or ambiguous endpoint shapes.
            IF jsonb_typeof(endpoint) IS DISTINCT FROM 'object' THEN
                RAISE EXCEPTION 'invalid workflow endpoint' USING ERRCODE = '23514';
            END IF;
            IF NOT (endpoint ?& ARRAY['integration_id','integration_kind','mapping_id','location','operation']) OR
               endpoint - ARRAY['integration_id','integration_kind','mapping_id','location','operation'] <> '{}'::jsonb OR
               NOT EXISTS (SELECT 1 FROM jsonb_array_elements(evidence->'dependencies') AS d
                           WHERE d.value = endpoint) THEN
                RAISE EXCEPTION 'unregistered workflow endpoint' USING ERRCODE = '23514';
            END IF;
        END LOOP;
    END LOOP;
    RETURN NEW;
END $$;
REVOKE ALL ON FUNCTION air.validate_workflow_edges() FROM PUBLIC;
CREATE TRIGGER workflow_edge_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_workflow_edges();
