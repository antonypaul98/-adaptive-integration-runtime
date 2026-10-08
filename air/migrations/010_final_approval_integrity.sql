-- Persisted final approval is an authenticated human attestation, never execution authority.
-- The trigger independently checks even direct SQL inserts, including the exact
-- reviewed bytes and every immutable upstream evidence link.
CREATE FUNCTION air.validate_final_approval_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; reviewed JSONB; proposal JSONB; decision JSONB;
    verification JSONB; sandbox JSONB;
    proposal_hash TEXT; decision_hash TEXT; verification_hash TEXT; sandbox_hash TEXT;
    proposal_id UUID; decision_id UUID; verification_id UUID; sandbox_id UUID;
    expected_keys TEXT[] := ARRAY[
        'tenant_id','final_approval_version','purpose','proposal','revision',
        'prior_proposal_decision','impact','change_evidence','sandbox','verification',
        'fixture_hash','review_hash','review_payload','confirmed','target','reviewer'];
    review_keys TEXT[] := ARRAY[
        'review_version','purpose','tenant_id','proposal','revision',
        'proposal_description','impact_item','impact','change_evidence',
        'prior_proposal_decision','sandbox','verification','fixture_hash','fixture','result'];
    target_keys TEXT[] := ARRAY['environment','integration_id','mapping_id','scope'];
    scope_key TEXT; scope_value JSONB;
BEGIN
    IF NEW.kind <> 'final_approval' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized final approval' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - expected_keys <> '{}'::jsonb OR NOT p ?& expected_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'final_approval_version' IS DISTINCT FROM 'air-final-approval-v1' OR
       p->>'purpose' IS DISTINCT FROM 'FINAL_APPROVAL_NO_DEPLOYMENT_EXECUTION' OR
       p->'confirmed' IS DISTINCT FROM 'true'::jsonb OR
       p->>'reviewer' IS DISTINCT FROM air.current_reviewer() OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash OR
       jsonb_typeof(p->'review_payload') IS DISTINCT FROM 'string' OR
       octet_length(p->>'review_payload') > 524288 OR
       p->>'review_hash' IS DISTINCT FROM
           encode(sha256(convert_to(p->>'review_payload','UTF8')),'hex') THEN
        RAISE EXCEPTION 'invalid final approval envelope' USING ERRCODE='23514';
    END IF;
    reviewed := (p->>'review_payload')::jsonb;
    IF jsonb_typeof(reviewed) IS DISTINCT FROM 'object' OR
       reviewed - review_keys <> '{}'::jsonb OR NOT reviewed ?& review_keys OR
       reviewed->>'review_version' IS DISTINCT FROM 'air-approval-review-v1' OR
       reviewed->>'purpose' IS DISTINCT FROM 'REVIEW_ONLY_NO_DEPLOYMENT_AUTHORITY' OR
       reviewed->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text THEN
        RAISE EXCEPTION 'invalid reviewed material' USING ERRCODE='23514';
    END IF;
    proposal_id := (p#>>'{proposal,artifact_id}')::uuid;
    PERFORM pg_advisory_xact_lock(
        hashtextextended(NEW.tenant_id::text || ':' || proposal_id::text,714208316));
    SELECT payload::jsonb,content_hash INTO proposal,proposal_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal'
        AND artifact_id=proposal_id;
    decision_id := (p#>>'{prior_proposal_decision,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO decision,decision_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_decision'
        AND artifact_id=decision_id;
    verification_id := (p#>>'{verification,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO verification,verification_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='replay_verification'
        AND artifact_id=verification_id;
    sandbox_id := (p#>>'{sandbox,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO sandbox,sandbox_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='sandbox_evaluation'
        AND artifact_id=sandbox_id;
    IF proposal IS NULL OR decision IS NULL OR verification IS NULL OR sandbox IS NULL OR
       p->'proposal' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',proposal_id::text,'artifact_hash',proposal_hash) OR
       p->'prior_proposal_decision' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',decision_id::text,'artifact_hash',decision_hash) OR
       p->'verification' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',verification_id::text,'artifact_hash',verification_hash) OR
       p->'sandbox' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',sandbox_id::text,'artifact_hash',sandbox_hash) OR
       p->'revision' IS DISTINCT FROM proposal->'revision' OR
       p->'impact' IS DISTINCT FROM proposal->'impact' OR
       p->'change_evidence' IS DISTINCT FROM proposal->'change_evidence' OR
       decision->>'decision' IS DISTINCT FROM 'APPROVED' OR
       decision->'proposal' IS DISTINCT FROM p->'proposal' OR
       decision->'revision' IS DISTINCT FROM p->'revision' OR
       decision->'impact' IS DISTINCT FROM p->'impact' OR
       decision->'change_evidence' IS DISTINCT FROM p->'change_evidence' OR
       verification#>>'{result,status}' IS DISTINCT FROM 'PASS' OR
       verification->'proposal' IS DISTINCT FROM p->'proposal' OR
       verification->'revision' IS DISTINCT FROM p->'revision' OR
       verification->'impact' IS DISTINCT FROM p->'impact' OR
       verification->'change_evidence' IS DISTINCT FROM p->'change_evidence' OR
       verification->'sandbox' IS DISTINCT FROM p->'sandbox' OR
       verification->>'fixture_hash' IS DISTINCT FROM p->>'fixture_hash' OR
       sandbox->'proposal' IS DISTINCT FROM p->'proposal' OR
       sandbox->'revision' IS DISTINCT FROM p->'revision' OR
       sandbox->'impact' IS DISTINCT FROM p->'impact' OR
       sandbox->'change_evidence' IS DISTINCT FROM p->'change_evidence' OR
       sandbox#>>'{result,status}' IS DISTINCT FROM 'PASS' OR
       EXISTS(SELECT 1 FROM air.artifacts
           WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal'
             AND payload::jsonb#>>'{supersedes,artifact_id}'=proposal_id::text) THEN
        RAISE EXCEPTION 'invalid or stale final approval binding' USING ERRCODE='23514';
    END IF;
    IF reviewed IS DISTINCT FROM jsonb_build_object(
        'review_version','air-approval-review-v1',
        'purpose','REVIEW_ONLY_NO_DEPLOYMENT_AUTHORITY',
        'tenant_id',NEW.tenant_id::text,
        'proposal',p->'proposal',
        'revision',proposal->'revision',
        'proposal_description',proposal->'description',
        'impact_item',proposal->'impact_item',
        'impact',proposal->'impact',
        'change_evidence',proposal->'change_evidence',
        'prior_proposal_decision',p->'prior_proposal_decision',
        'sandbox',p->'sandbox',
        'verification',p->'verification',
        'fixture_hash',verification->'fixture_hash',
        'fixture',verification->'fixture',
        'result',verification->'result') THEN
        RAISE EXCEPTION 'review material differs from immutable evidence' USING ERRCODE='23514';
    END IF;
    IF jsonb_typeof(p->'target') IS DISTINCT FROM 'object' OR
       p->'target' - target_keys <> '{}'::jsonb OR NOT p->'target' ?& target_keys OR
       p#>>'{target,integration_id}' IS DISTINCT FROM
           proposal#>>'{impact_item,dependency,integration_id}' OR
       p#>>'{target,mapping_id}' IS DISTINCT FROM
           proposal#>>'{impact_item,dependency,mapping_id}' OR
       jsonb_typeof(p#>'{target,environment}') IS DISTINCT FROM 'string' OR
       length(btrim(p#>>'{target,environment}')) NOT BETWEEN 1 AND 128 OR
       (p#>>'{target,environment}') ~ '[[:cntrl:]]' OR
       jsonb_typeof(p#>'{target,scope}') IS DISTINCT FROM 'object' OR
       (SELECT count(*) FROM jsonb_object_keys(p#>'{target,scope}')) NOT BETWEEN 1 AND 32 OR
       octet_length((p#>'{target,scope}')::text) > 16384 THEN
        RAISE EXCEPTION 'invalid final approval target' USING ERRCODE='23514';
    END IF;
    FOR scope_key,scope_value IN SELECT key,value FROM jsonb_each(p#>'{target,scope}') LOOP
        IF length(btrim(scope_key)) NOT BETWEEN 1 AND 128 OR
           scope_key ~ '[[:cntrl:]]' OR
           jsonb_typeof(scope_value) NOT IN ('string','number','boolean') OR
           (jsonb_typeof(scope_value)='string' AND
              (length(btrim(scope_value#>>'{}')) NOT BETWEEN 1 AND 1024 OR
               (scope_value#>>'{}') ~ '[[:cntrl:]]')) OR
           (jsonb_typeof(scope_value)='number' AND
              (scope_value::text !~ '^-?[0-9]+$' OR
               length(scope_value::text)>100)) THEN
            RAISE EXCEPTION 'invalid final approval scope' USING ERRCODE='23514';
        END IF;
    END LOOP;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range OR invalid_parameter_value THEN
    RAISE EXCEPTION 'invalid final approval reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_final_approval_links() FROM PUBLIC;
CREATE TRIGGER final_approval_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_final_approval_links();
