-- Forward correction: preserve migration 007 checksums for existing databases.
CREATE OR REPLACE FUNCTION air.validate_sandbox_evaluation_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE p JSONB; proposal JSONB; proposal_hash TEXT; ref UUID; expected_keys TEXT[];
    state_text TEXT; state JSONB; node_count INTEGER; deepest INTEGER;
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
    -- Serialize with proposal supersession and human approval (migration 006).
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || ':' || ref::text,714208316));
    SELECT payload::jsonb, content_hash, (payload::json#>'{description,proposed_state}')::text
      INTO proposal, proposal_hash, state_text
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
    IF NOT EXISTS(SELECT 1 FROM air.artifacts
        WHERE tenant_id=NEW.tenant_id AND kind='repair_decision'
          AND payload::jsonb->>'decision'='APPROVED'
          AND payload::jsonb->'proposal'=p->'proposal'
          AND payload::jsonb->'revision'=p->'revision'
          AND payload::jsonb->'impact'=p->'impact'
          AND payload::jsonb->'change_evidence'=p->'change_evidence') THEN
        RAISE EXCEPTION 'sandbox proposal is not approved' USING ERRCODE='23514';
    END IF;
    state := proposal#>'{description,proposed_state}';
    -- JSON extraction preserves the canonical bytes stored in the proposal.
    IF octet_length(state_text) > 65536 OR
       p#>>'{result,state_hash}' IS DISTINCT FROM
         encode(sha256(convert_to(state_text,'UTF8')),'hex') THEN
        RAISE EXCEPTION 'invalid sandbox state hash or size' USING ERRCODE='23514';
    END IF;
    WITH RECURSIVE walk(value,depth) AS (
        SELECT state,0
        UNION ALL
        SELECT child.value,walk.depth+1 FROM walk CROSS JOIN LATERAL (
            SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(walk.value)='object'
                THEN walk.value ELSE '{}'::jsonb END)
            UNION ALL
            SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(walk.value)='array'
                THEN walk.value ELSE '[]'::jsonb END)
        ) child WHERE walk.depth <= 16
    ) SELECT count(*),max(depth) INTO node_count,deepest
        FROM (SELECT depth FROM walk LIMIT 4097) bounded;
    IF node_count > 4096 OR deepest > 16 THEN
        RAISE EXCEPTION 'sandbox structural bounds exceeded' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'invalid sandbox reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_sandbox_evaluation_links() FROM PUBLIC;
