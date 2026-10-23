-- Persist deterministic AIR-25 projections through tenant RLS and append-only audit.
CREATE FUNCTION air.validate_dependency_projection() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; projection JSONB; registry JSONB; impact JSONB;
    expected_impact_hash JSONB := 'null'::jsonb;
    registry_hash TEXT; impact_hash TEXT; registry_id UUID; impact_id UUID;
    root_keys TEXT[] := ARRAY['tenant_id','projection_record_version','registry',
                              'impact','projection_hash','projection_payload'];
BEGIN
    IF NEW.kind <> 'dependency_projection' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized dependency projection' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - root_keys <> '{}'::jsonb OR NOT p ?& root_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'projection_record_version' IS DISTINCT FROM
           'air-dependency-projection-record-v1' OR
       jsonb_typeof(p->'registry') IS DISTINCT FROM 'object' OR
       (p->'registry') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
       NOT (p->'registry' ?& ARRAY['artifact_id','artifact_hash']) OR
       (p#>>'{registry,artifact_hash}') !~ '^[0-9a-f]{64}$' OR
       (p->>'projection_hash') !~ '^[0-9a-f]{64}$' OR
       jsonb_typeof(p->'projection_payload') IS DISTINCT FROM 'string' OR
       octet_length(p->>'projection_payload') > 1048576 OR
       p->>'projection_hash' IS DISTINCT FROM
           encode(sha256(convert_to(p->>'projection_payload','UTF8')),'hex') OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid dependency projection envelope' USING ERRCODE='23514';
    END IF;

    registry_id := (p#>>'{registry,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO registry,registry_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='contract_dependency_registry' AND artifact_id=registry_id;
    IF registry IS NULL OR p->'registry' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',registry_id::text,'artifact_hash',registry_hash) THEN
        RAISE EXCEPTION 'unbound dependency projection registry' USING ERRCODE='23514';
    END IF;

    IF p->'impact' <> 'null'::jsonb THEN
        IF jsonb_typeof(p->'impact') IS DISTINCT FROM 'object' OR
           (p->'impact') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
           NOT (p->'impact' ?& ARRAY['artifact_id','artifact_hash']) OR
           (p#>>'{impact,artifact_hash}') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'invalid dependency projection impact' USING ERRCODE='23514';
        END IF;
        impact_id := (p#>>'{impact,artifact_id}')::uuid;
        SELECT payload::jsonb,content_hash INTO impact,impact_hash
          FROM air.artifacts WHERE tenant_id=NEW.tenant_id
            AND kind='contract_dependency_impact' AND artifact_id=impact_id;
        IF impact IS NULL OR p->'impact' IS DISTINCT FROM jsonb_build_object(
               'artifact_id',impact_id::text,'artifact_hash',impact_hash) OR
           impact->'registry' IS DISTINCT FROM p->'registry' THEN
            RAISE EXCEPTION 'unbound dependency projection impact' USING ERRCODE='23514';
        END IF;
        expected_impact_hash := to_jsonb(impact->>'impact_hash');
    END IF;

    projection := (p->>'projection_payload')::jsonb;
    IF jsonb_typeof(projection) IS DISTINCT FROM 'object' OR
       projection->>'projection_version' IS DISTINCT FROM
           'air-dependency-projection-v1' OR
       projection#>>'{coverage,scope}' IS DISTINCT FROM 'explicit_registry_only' OR
       projection#>'{coverage,no_recorded_impact_is_not_safe}' IS DISTINCT FROM 'true'::jsonb OR
       projection#>'{coverage,dependency_discovery_performed}' IS DISTINCT FROM 'false'::jsonb OR
       projection->'authority' IS DISTINCT FROM jsonb_build_object(
           'read_only',true,'external_actions',false,
           'repair_authority',false,'deployment_authority',false) OR
       projection->'impact_report_hash' IS DISTINCT FROM expected_impact_hash THEN
        RAISE EXCEPTION 'invalid dependency projection payload' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN
    RAISE EXCEPTION 'invalid dependency projection reference' USING ERRCODE='23514';
END; $$;
REVOKE ALL ON FUNCTION air.validate_dependency_projection() FROM PUBLIC;
CREATE TRIGGER dependency_projection_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_dependency_projection();
