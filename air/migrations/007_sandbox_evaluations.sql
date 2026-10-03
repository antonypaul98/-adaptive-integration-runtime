-- Database-enforced integrity for immutable bounded sandbox evaluation evidence.
CREATE UNIQUE INDEX sandbox_one_evaluation ON air.artifacts
    (tenant_id, (payload::jsonb#>>'{proposal,artifact_id}'))
    WHERE kind='sandbox_evaluation';

CREATE FUNCTION air.validate_sandbox_evaluation_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE p JSONB; proposal JSONB; proposal_hash TEXT; ref UUID; expected_keys TEXT[];
BEGIN
    IF NEW.kind <> 'sandbox_evaluation' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized sandbox evidence' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    expected_keys := ARRAY['tenant_id','sandbox_version','proposal','revision','impact','change_evidence','result'];
    IF p - expected_keys <> '{}'::jsonb OR NOT p ?& expected_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'sandbox_version' IS DISTINCT FROM 'air-sandbox-evaluation-v1' OR
       jsonb_typeof(p->'revision') IS DISTINCT FROM 'number' OR
       (p->>'revision') !~ '^[1-9][0-9]{0,2}$' OR
       jsonb_typeof(p->'proposal') IS DISTINCT FROM 'object' OR
       jsonb_typeof(p->'impact') IS DISTINCT FROM 'object' OR
       jsonb_typeof(p->'change_evidence') IS DISTINCT FROM 'object' OR
       jsonb_typeof(p->'result') IS DISTINCT FROM 'object' OR
       p#>>'{result,status}' IS DISTINCT FROM 'PASS' OR
       jsonb_typeof(p#>'{result,state_hash}') IS DISTINCT FROM 'string' OR
       (p#>>'{result,state_hash}') !~ '^[0-9a-f]{64}$' OR
       p#>'{result,checks}' IS DISTINCT FROM
          '["canonical_state","bounded_structure","declarative_only"]'::jsonb OR
       (p->'result') - ARRAY['status','state_hash','checks'] <> '{}'::jsonb OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid sandbox evidence' USING ERRCODE='23514';
    END IF;

    ref := (p#>>'{proposal,artifact_id}')::uuid;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || ':' || ref::text,714208317));
    SELECT payload::jsonb, content_hash INTO proposal, proposal_hash
      FROM air.artifacts
     WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal' AND artifact_id=ref;

    IF proposal IS NULL OR
       p->'proposal' IS DISTINCT FROM jsonb_build_object('artifact_id',ref::text,'artifact_hash',proposal_hash) OR
       p->'revision' IS DISTINCT FROM proposal->'revision' OR
       p->'impact' IS DISTINCT FROM proposal->'impact' OR
       p->'change_evidence' IS DISTINCT FROM proposal->'change_evidence' OR
       EXISTS(SELECT 1 FROM air.artifacts
               WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal'
                 AND payload::jsonb#>>'{supersedes,artifact_id}'=ref::text) THEN
        RAISE EXCEPTION 'invalid or stale sandbox evidence' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'invalid sandbox reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_sandbox_evaluation_links() FROM PUBLIC;
CREATE TRIGGER sandbox_evaluation_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_sandbox_evaluation_links();
