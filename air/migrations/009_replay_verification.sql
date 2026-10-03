-- Append-only replay evidence inherits artifact RLS, hash generation and audit.
-- Validate even direct SQL inserts; no caller-supplied PASS is trusted.
CREATE FUNCTION air.validate_replay_verification() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; proposal JSONB; sandbox JSONB; proposal_json JSON; ref UUID;
    proposal_hash TEXT; sandbox_hash TEXT; fixture JSON; c JSON; cb JSONB;
    actual JSON; expected JSON; k JSONB; key TEXT; previous_id TEXT := '';
    actual_hash TEXT; expected_hash TEXT; rows JSONB := '[]'; result JSONB;
    all_match BOOLEAN := true; nodes INTEGER; deepest INTEGER;
    keys TEXT[] := ARRAY['tenant_id','replay_version','proposal','revision','sandbox',
                         'impact','change_evidence','fixture','fixture_hash','result'];
BEGIN
    IF NEW.kind <> 'replay_verification' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized replay' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - keys <> '{}'::jsonb OR NOT p ?& keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'replay_version' IS DISTINCT FROM 'air-replay-verification-v1' OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid replay envelope' USING ERRCODE='23514';
    END IF;
    ref := (p#>>'{proposal,artifact_id}')::uuid;
    PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || ':' || ref::text,714208316));
    SELECT payload::jsonb, payload::json, content_hash INTO proposal, proposal_json, proposal_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal' AND artifact_id=ref;
    SELECT payload::jsonb, content_hash INTO sandbox, sandbox_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='sandbox_evaluation'
        AND artifact_id=(p#>>'{sandbox,artifact_id}')::uuid;
    IF proposal IS NULL OR sandbox IS NULL OR
       p->'proposal' IS DISTINCT FROM jsonb_build_object('artifact_id',ref::text,'artifact_hash',proposal_hash) OR
       p->'sandbox' IS DISTINCT FROM jsonb_build_object('artifact_id',p#>>'{sandbox,artifact_id}','artifact_hash',sandbox_hash) OR
       p->'revision' IS DISTINCT FROM proposal->'revision' OR
       p->'impact' IS DISTINCT FROM proposal->'impact' OR
       p->'change_evidence' IS DISTINCT FROM proposal->'change_evidence' OR
       sandbox->'proposal' IS DISTINCT FROM p->'proposal' OR
       sandbox->'revision' IS DISTINCT FROM p->'revision' OR
       sandbox->'impact' IS DISTINCT FROM p->'impact' OR
       sandbox->'change_evidence' IS DISTINCT FROM p->'change_evidence' OR
       sandbox#>>'{result,status}' IS DISTINCT FROM 'PASS' OR
       EXISTS(SELECT 1 FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal'
           AND payload::jsonb#>>'{supersedes,artifact_id}'=ref::text) OR
       NOT EXISTS(SELECT 1 FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_decision'
           AND payload::jsonb->>'decision'='APPROVED'
           AND payload::jsonb->'proposal'=p->'proposal'
           AND payload::jsonb->'revision'=p->'revision'
           AND payload::jsonb->'impact'=p->'impact'
           AND payload::jsonb->'change_evidence'=p->'change_evidence') THEN
        RAISE EXCEPTION 'stale or unapproved replay binding' USING ERRCODE='23514';
    END IF;
    fixture := NEW.payload::json->'fixture';
    IF jsonb_typeof(p->'fixture') IS DISTINCT FROM 'object' OR
       (p->'fixture') - ARRAY['version','cases'] <> '{}'::jsonb OR
       p#>>'{fixture,version}' IS DISTINCT FROM 'air-replay-verification-v1' OR
       jsonb_typeof(p#>'{fixture,cases}') IS DISTINCT FROM 'array' OR
       octet_length(fixture::text) > 65536 OR
       p->>'fixture_hash' IS DISTINCT FROM encode(sha256(convert_to(fixture::text,'UTF8')),'hex') THEN
        RAISE EXCEPTION 'invalid replay fixture' USING ERRCODE='23514';
    END IF;
    IF jsonb_array_length(p#>'{fixture,cases}') NOT BETWEEN 1 AND 32 THEN
        RAISE EXCEPTION 'replay case bound' USING ERRCODE='23514';
    END IF;
    WITH RECURSIVE walk(value,depth) AS (
        SELECT fixture::jsonb,0 UNION ALL
        SELECT child.value,walk.depth+1 FROM walk CROSS JOIN LATERAL (
            SELECT value FROM jsonb_each(CASE WHEN jsonb_typeof(walk.value)='object' THEN walk.value ELSE '{}'::jsonb END)
            UNION ALL
            SELECT value FROM jsonb_array_elements(CASE WHEN jsonb_typeof(walk.value)='array' THEN walk.value ELSE '[]'::jsonb END)
        ) child WHERE walk.depth <= 16
    ) SELECT count(*),max(depth) INTO nodes,deepest FROM (SELECT depth FROM walk LIMIT 4097) bounded;
    IF nodes > 4096 OR deepest > 16 THEN
        RAISE EXCEPTION 'replay structural bound' USING ERRCODE='23514';
    END IF;
    FOR c IN SELECT value FROM json_array_elements(fixture->'cases') LOOP
        cb := c::jsonb;
        IF jsonb_typeof(cb) IS DISTINCT FROM 'object' OR
           cb - ARRAY['case_id','input','expected'] <> '{}'::jsonb OR
           NOT cb ?& ARRAY['case_id','input','expected'] OR
           jsonb_typeof(cb->'case_id') IS DISTINCT FROM 'string' OR
           (cb->>'case_id') !~ '^[A-Za-z0-9_.-]{1,64}$' OR
           (cb->>'case_id') COLLATE "C" <= previous_id COLLATE "C" OR
           jsonb_typeof(cb->'input') IS DISTINCT FROM 'object' OR
           (cb->'input') - 'path' <> '{}'::jsonb OR
           jsonb_typeof(cb#>'{input,path}') IS DISTINCT FROM 'array' THEN
            RAISE EXCEPTION 'invalid or unordered replay case' USING ERRCODE='23514';
        END IF;
        previous_id := cb->>'case_id';
        IF jsonb_array_length(cb#>'{input,path}') NOT BETWEEN 1 AND 16 THEN
            RAISE EXCEPTION 'invalid replay path bound' USING ERRCODE='23514';
        END IF;
        actual := proposal_json#>'{description,proposed_state}';
        FOR k IN SELECT value FROM jsonb_array_elements(cb#>'{input,path}') LOOP
            key := k#>>'{}';
            IF jsonb_typeof(k) IS DISTINCT FROM 'string' OR length(key) NOT BETWEEN 1 AND 128 OR
               json_typeof(actual) IS DISTINCT FROM 'object' OR NOT actual::jsonb ? key THEN
                RAISE EXCEPTION 'unsupported or missing replay path' USING ERRCODE='23514';
            END IF;
            actual := actual->key;
        END LOOP;
        expected := c->'expected';
        actual_hash := encode(sha256(convert_to(actual::text,'UTF8')),'hex');
        expected_hash := encode(sha256(convert_to(expected::text,'UTF8')),'hex');
        all_match := all_match AND actual_hash=expected_hash;
        rows := rows || jsonb_build_array(jsonb_build_object('case_id',previous_id,
            'actual_hash',actual_hash,'expected_hash',expected_hash,'matches',actual_hash=expected_hash));
    END LOOP;
    result := jsonb_build_object('status',CASE WHEN all_match THEN 'PASS' ELSE 'FAIL' END,'cases',rows);
    IF p->'result' IS DISTINCT FROM result THEN
        RAISE EXCEPTION 'forged replay result' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'invalid replay reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_replay_verification() FROM PUBLIC;
CREATE TRIGGER replay_verification_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_replay_verification();
