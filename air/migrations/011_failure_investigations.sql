-- Persist redacted failure investigations through existing append-only evidence,
-- tenant RLS and audit. This is diagnostic evidence, never repair authority.
CREATE FUNCTION air.validate_failure_investigation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; report JSONB; verification JSONB; finding JSONB; replay_case JSONB;
    verification_hash TEXT; fixture_hash TEXT; expected_finding_id TEXT;
    verification_id UUID; previous_case_id TEXT := ''; failing_count INTEGER := 0;
    finding_count INTEGER := 0;
    root_keys TEXT[] := ARRAY['tenant_id','investigation_record_version','verification',
                              'report_hash','report_payload'];
    report_keys TEXT[] := ARRAY['investigation_version','source','findings','coverage',
                                'uncertainty','review_required','authority'];
BEGIN
    IF NEW.kind <> 'failure_investigation' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized failure investigation' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - root_keys <> '{}'::jsonb OR NOT p ?& root_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'investigation_record_version' IS DISTINCT FROM
           'air-failure-investigation-record-v1' OR
       jsonb_typeof(p->'verification') IS DISTINCT FROM 'object' OR
       (p->'verification') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
       NOT (p->'verification' ?& ARRAY['artifact_id','artifact_hash']) OR
       (p#>>'{verification,artifact_hash}') !~ '^[0-9a-f]{64}$' OR
       (p->>'report_hash') !~ '^[0-9a-f]{64}$' OR
       jsonb_typeof(p->'report_payload') IS DISTINCT FROM 'string' OR
       octet_length(p->>'report_payload') > 262144 OR
       p->>'report_hash' IS DISTINCT FROM
           encode(sha256(convert_to(p->>'report_payload','UTF8')),'hex') OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid failure investigation envelope' USING ERRCODE='23514';
    END IF;

    verification_id := (p#>>'{verification,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO verification,verification_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='replay_verification' AND artifact_id=verification_id;
    IF verification IS NULL OR p->'verification' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',verification_id::text,'artifact_hash',verification_hash) THEN
        RAISE EXCEPTION 'unbound replay investigation' USING ERRCODE='23514';
    END IF;

    report := (p->>'report_payload')::jsonb;
    fixture_hash := verification->>'fixture_hash';
    IF jsonb_typeof(report) IS DISTINCT FROM 'object' OR
       report - report_keys <> '{}'::jsonb OR NOT report ?& report_keys OR
       report->>'investigation_version' IS DISTINCT FROM 'air-failure-investigation-v1' OR
       report->>'authority' IS DISTINCT FROM
           'DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY' OR
       report->'source' IS DISTINCT FROM jsonb_build_object(
           'kind','bounded_replay_result',
           'replay_version','air-replay-verification-v1',
           'fixture_hash',fixture_hash,
           'status',verification#>>'{result,status}') OR
       jsonb_typeof(report->'findings') IS DISTINCT FROM 'array' OR
       report->'uncertainty' IS DISTINCT FROM jsonb_build_array(
           'A value mismatch does not identify which component caused the difference.',
           'Passing recorded cases do not prove unrecorded behavior is safe.') THEN
        RAISE EXCEPTION 'invalid failure investigation report' USING ERRCODE='23514';
    END IF;

    FOR replay_case IN SELECT value FROM jsonb_array_elements(verification#>'{result,cases}') LOOP
        IF replay_case->'matches' = 'false'::jsonb THEN failing_count := failing_count + 1; END IF;
    END LOOP;
    IF report->'coverage' IS DISTINCT FROM jsonb_build_object(
           'analyzed_cases',jsonb_array_length(verification#>'{result,cases}'),
           'failing_cases',failing_count,
           'scope','recorded_projection_cases_only',
           'root_cause_coverage','NOT_ESTABLISHED') OR
       report->'review_required' IS DISTINCT FROM to_jsonb(failing_count > 0) OR
       jsonb_array_length(report->'findings') <> failing_count THEN
        RAISE EXCEPTION 'inconsistent failure investigation coverage' USING ERRCODE='23514';
    END IF;

    FOR finding IN SELECT value FROM jsonb_array_elements(report->'findings') LOOP
        IF jsonb_typeof(finding) IS DISTINCT FROM 'object' OR
           finding - ARRAY['finding_id','case_id','code','confidence','evidence','explanation']
               <> '{}'::jsonb OR
           NOT finding ?& ARRAY['finding_id','case_id','code','confidence','evidence','explanation'] OR
           (finding->>'case_id') !~ '^[A-Za-z0-9_.-]{1,64}$' OR
           (finding->>'case_id') COLLATE "C" <= previous_case_id COLLATE "C" OR
           finding->>'code' IS DISTINCT FROM 'RECORDED_VALUE_MISMATCH' OR
           finding->>'confidence' IS DISTINCT FROM 'CONFIRMED' OR
           finding->>'explanation' IS DISTINCT FROM
               'The bounded recorded projection differs from its exact expected value.' OR
           jsonb_typeof(finding->'evidence') IS DISTINCT FROM 'object' OR
           (finding->'evidence') - ARRAY['actual_hash','expected_hash'] <> '{}'::jsonb OR
           NOT (finding->'evidence' ?& ARRAY['actual_hash','expected_hash']) OR
           (finding#>>'{evidence,actual_hash}') !~ '^[0-9a-f]{64}$' OR
           (finding#>>'{evidence,expected_hash}') !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'invalid failure investigation finding' USING ERRCODE='23514';
        END IF;
        SELECT value INTO replay_case FROM jsonb_array_elements(verification#>'{result,cases}')
          WHERE value->>'case_id'=finding->>'case_id' AND value->'matches'='false'::jsonb
          LIMIT 1;
        IF replay_case IS NULL OR finding->'evidence' IS DISTINCT FROM jsonb_build_object(
               'actual_hash',replay_case->>'actual_hash',
               'expected_hash',replay_case->>'expected_hash') THEN
            RAISE EXCEPTION 'unbound failure investigation finding' USING ERRCODE='23514';
        END IF;
        expected_finding_id := encode(sha256(convert_to(
            '{"case_id":' || to_json(finding->>'case_id')::text ||
            ',"code":"RECORDED_VALUE_MISMATCH","evidence":{"actual_hash":"' ||
            (replay_case->>'actual_hash') || '","expected_hash":"' ||
            (replay_case->>'expected_hash') || '"},"fixture_hash":"' || fixture_hash || '"}',
            'UTF8')),'hex');
        IF finding->>'finding_id' IS DISTINCT FROM expected_finding_id THEN
            RAISE EXCEPTION 'invalid failure investigation finding identity' USING ERRCODE='23514';
        END IF;
        previous_case_id := finding->>'case_id';
        finding_count := finding_count + 1;
    END LOOP;
    IF finding_count <> failing_count THEN
        RAISE EXCEPTION 'missing failure investigation finding' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN
    RAISE EXCEPTION 'invalid failure investigation reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_failure_investigation() FROM PUBLIC;
CREATE TRIGGER failure_investigation_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_failure_investigation();
