-- Bind redacted AIR-25 visualization evidence to one tenant projection.
CREATE FUNCTION air.validate_dependency_visualization() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; visualization JSONB; projection JSONB;
    projection_hash TEXT; projection_id UUID;
    root_keys TEXT[] := ARRAY['tenant_id','visualization_record_version',
                              'projection','visualization_hash','visualization_payload'];
BEGIN
    IF NEW.kind <> 'dependency_visualization' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized dependency visualization' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - root_keys <> '{}'::jsonb OR NOT p ?& root_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'visualization_record_version' IS DISTINCT FROM
           'air-dependency-visualization-record-v1' OR
       jsonb_typeof(p->'projection') IS DISTINCT FROM 'object' OR
       (p->'projection') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
       NOT (p->'projection' ?& ARRAY['artifact_id','artifact_hash']) OR
       (p#>>'{projection,artifact_hash}') !~ '^[0-9a-f]{64}$' OR
       (p->>'visualization_hash') !~ '^[0-9a-f]{64}$' OR
       jsonb_typeof(p->'visualization_payload') IS DISTINCT FROM 'string' OR
       octet_length(p->>'visualization_payload') > 1048576 OR
       p->>'visualization_hash' IS DISTINCT FROM
           encode(sha256(convert_to(p->>'visualization_payload','UTF8')),'hex') OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid dependency visualization envelope' USING ERRCODE='23514';
    END IF;

    projection_id := (p#>>'{projection,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO projection,projection_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='dependency_projection' AND artifact_id=projection_id;
    IF projection IS NULL OR p->'projection' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',projection_id::text,'artifact_hash',projection_hash) THEN
        RAISE EXCEPTION 'unbound dependency visualization projection' USING ERRCODE='23514';
    END IF;

    visualization := (p->>'visualization_payload')::jsonb;
    IF jsonb_typeof(visualization) IS DISTINCT FROM 'object' OR
       visualization->>'visualization_version' IS DISTINCT FROM
           'air-dependency-visualization-v1' OR
       visualization->>'projection_hash' IS DISTINCT FROM
           projection->>'projection_hash' OR
       visualization#>>'{coverage,scope}' IS DISTINCT FROM
           'validated_explicit_projection_only' OR
       visualization#>'{coverage,raw_dependency_metadata_included}' IS DISTINCT FROM
           'false'::jsonb OR
       visualization#>'{coverage,projection_origin_authenticated}' IS DISTINCT FROM
           'false'::jsonb OR
       visualization#>'{coverage,no_recorded_impact_is_not_safe}' IS DISTINCT FROM
           'true'::jsonb OR
       visualization->'authority' IS DISTINCT FROM jsonb_build_object(
           'read_only',true,'external_actions',false,
           'repair_authority',false,'deployment_authority',false) THEN
        RAISE EXCEPTION 'invalid dependency visualization payload' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN
    RAISE EXCEPTION 'invalid dependency visualization reference' USING ERRCODE='23514';
END; $$;
REVOKE ALL ON FUNCTION air.validate_dependency_visualization() FROM PUBLIC;
CREATE TRIGGER dependency_visualization_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_dependency_visualization();
