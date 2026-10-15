-- Persist caller-declared failure candidates as tenant-scoped diagnostic evidence.
-- Correlation is never causal proof and grants no repair or execution authority.
CREATE FUNCTION air.validate_failure_candidate_correlation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    p JSONB; investigation JSONB; impact JSONB; report JSONB; correlation JSONB;
    source JSONB; link JSONB; candidate JSONB; finding JSONB; impact_item JSONB;
    investigation_hash TEXT; impact_hash TEXT; expected_candidate_id TEXT;
    investigation_id UUID; impact_id UUID; previous_link TEXT := '';
    linked_count INTEGER; finding_count INTEGER; unmatched JSONB;
    root_keys TEXT[] := ARRAY['tenant_id','correlation_record_version','investigation',
        'impact','declared_links','correlation_hash','correlation_payload'];
    correlation_keys TEXT[] := ARRAY['correlation_version','source','candidates','coverage',
        'uncertainty','review_required','authority'];
BEGIN
    IF NEW.kind <> 'failure_candidate_correlation' THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized failure correlation' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p - root_keys <> '{}'::jsonb OR NOT p ?& root_keys OR
       p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'correlation_record_version' IS DISTINCT FROM
           'air-failure-correlation-record-v1' OR
       jsonb_typeof(p->'investigation') IS DISTINCT FROM 'object' OR
       (p->'investigation') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
       NOT (p->'investigation' ?& ARRAY['artifact_id','artifact_hash']) OR
       jsonb_typeof(p->'impact') IS DISTINCT FROM 'object' OR
       (p->'impact') - ARRAY['artifact_id','artifact_hash'] <> '{}'::jsonb OR
       NOT (p->'impact' ?& ARRAY['artifact_id','artifact_hash']) OR
       (p#>>'{investigation,artifact_hash}') !~ '^[0-9a-f]{64}$' OR
       (p#>>'{impact,artifact_hash}') !~ '^[0-9a-f]{64}$' OR
       jsonb_typeof(p->'declared_links') IS DISTINCT FROM 'array' OR
       jsonb_array_length(p->'declared_links') > 128 OR
       (p->>'correlation_hash') !~ '^[0-9a-f]{64}$' OR
       jsonb_typeof(p->'correlation_payload') IS DISTINCT FROM 'string' OR
       octet_length(p->>'correlation_payload') > 524288 OR
       p->>'correlation_hash' IS DISTINCT FROM
           encode(sha256(convert_to(p->>'correlation_payload','UTF8')),'hex') OR
       NEW.idempotency_key IS DISTINCT FROM NEW.content_hash THEN
        RAISE EXCEPTION 'invalid failure correlation envelope' USING ERRCODE='23514';
    END IF;

    investigation_id := (p#>>'{investigation,artifact_id}')::uuid;
    impact_id := (p#>>'{impact,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO investigation,investigation_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='failure_investigation' AND artifact_id=investigation_id;
    SELECT payload::jsonb,content_hash INTO impact,impact_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='contract_dependency_impact' AND artifact_id=impact_id;
    IF investigation IS NULL OR impact IS NULL OR
       p->'investigation' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',investigation_id::text,'artifact_hash',investigation_hash) OR
       p->'impact' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',impact_id::text,'artifact_hash',impact_hash) THEN
        RAISE EXCEPTION 'unbound failure correlation' USING ERRCODE='23514';
    END IF;

    report := (investigation->>'report_payload')::jsonb;
    correlation := (p->>'correlation_payload')::jsonb;
    source := correlation->'source';
    IF jsonb_typeof(correlation) IS DISTINCT FROM 'object' OR
       correlation - correlation_keys <> '{}'::jsonb OR NOT correlation ?& correlation_keys OR
       correlation->>'correlation_version' IS DISTINCT FROM 'air-failure-correlation-v1' OR
       correlation->>'authority' IS DISTINCT FROM
           'DIAGNOSTIC_ONLY_NO_REPAIR_OR_EXECUTION_AUTHORITY' OR
       jsonb_typeof(source) IS DISTINCT FROM 'object' OR
       source IS DISTINCT FROM jsonb_build_object(
           'investigation_hash',investigation->>'report_hash',
           'fixture_hash',report#>>'{source,fixture_hash}',
           'change_set_hash',impact#>>'{analysis,change_set_hash}',
           'impact_report_hash',impact->>'impact_hash',
           'impact_version',impact#>>'{analysis,impact_version}') OR
       jsonb_typeof(correlation->'candidates') IS DISTINCT FROM 'array' OR
       jsonb_array_length(correlation->'candidates') <> jsonb_array_length(p->'declared_links') OR
       correlation->'uncertainty' IS DISTINCT FROM jsonb_build_array(
           'A declared dependency correlation is not evidence that a change caused a failure.',
           'Unregistered dependencies, unchanged behavior, environment, data, and timing remain outside this correlation.') OR
       correlation->'review_required' IS DISTINCT FROM
           to_jsonb(jsonb_array_length(report->'findings') > 0) THEN
        RAISE EXCEPTION 'invalid failure correlation report' USING ERRCODE='23514';
    END IF;

    FOR link IN SELECT value FROM jsonb_array_elements(p->'declared_links') LOOP
        IF jsonb_typeof(link) IS DISTINCT FROM 'object' OR
           link - ARRAY['case_id','impact_id','basis'] <> '{}'::jsonb OR
           NOT link ?& ARRAY['case_id','impact_id','basis'] OR
           (link->>'case_id') !~ '^[A-Za-z0-9_.-]{1,64}$' OR
           (link->>'impact_id') !~ '^[0-9a-f]{64}$' OR
           link->>'basis' IS DISTINCT FROM 'DECLARED_TEST_DEPENDENCY' OR
           ((link->>'case_id') || ':' || (link->>'impact_id') || ':' || (link->>'basis'))
               COLLATE "C" <= previous_link COLLATE "C" THEN
            RAISE EXCEPTION 'invalid declared failure link' USING ERRCODE='23514';
        END IF;
        SELECT value INTO finding FROM jsonb_array_elements(report->'findings')
          WHERE value->>'case_id'=link->>'case_id' LIMIT 1;
        SELECT value INTO impact_item FROM (
            SELECT value FROM jsonb_array_elements(impact#>'{analysis,impacts}')
            UNION ALL
            SELECT value FROM jsonb_array_elements(
                COALESCE(impact#>'{analysis,downstream_impacts}','[]'::jsonb))
        ) AS impact_rows WHERE value->>'impact_id'=link->>'impact_id' LIMIT 1;
        SELECT value INTO candidate FROM jsonb_array_elements(correlation->'candidates')
          WHERE value->>'case_id'=link->>'case_id'
            AND value#>>'{evidence,impact_id}'=link->>'impact_id'
            AND value->>'basis'=link->>'basis' LIMIT 1;
        IF finding IS NULL OR impact_item IS NULL OR candidate IS NULL OR
           candidate - ARRAY['candidate_id','case_id','basis','impact_match','classification',
                             'confidence','evidence'] <> '{}'::jsonb OR
           NOT candidate ?& ARRAY['candidate_id','case_id','basis','impact_match','classification',
                                 'confidence','evidence'] OR
           candidate->>'confidence' IS DISTINCT FROM
               'SUPPORTED_CORRELATION_NOT_CAUSAL_PROOF' OR
           candidate->>'impact_match' IS DISTINCT FROM impact_item->>'match' OR
           candidate->>'classification' IS DISTINCT FROM impact_item->>'classification' OR
           candidate->'evidence' IS DISTINCT FROM jsonb_build_object(
               'finding_id',finding->>'finding_id',
               'impact_id',impact_item->>'impact_id',
               'change_id',impact_item->>'change_id') THEN
            RAISE EXCEPTION 'unbound failure candidate' USING ERRCODE='23514';
        END IF;
        expected_candidate_id := encode(sha256(convert_to(
            '{"basis":"DECLARED_TEST_DEPENDENCY","case_id":' ||
            to_json(candidate->>'case_id')::text ||
            ',"evidence":{"change_id":"' || (impact_item->>'change_id') ||
            '","finding_id":"' || (finding->>'finding_id') ||
            '","impact_id":"' || (impact_item->>'impact_id') ||
            '"},"source":{"change_set_hash":"' || (source->>'change_set_hash') ||
            '","fixture_hash":"' || (source->>'fixture_hash') ||
            '","impact_report_hash":"' || (source->>'impact_report_hash') ||
            '","impact_version":"' || (source->>'impact_version') ||
            '","investigation_hash":"' || (source->>'investigation_hash') || '"}}',
            'UTF8')),'hex');
        IF candidate->>'candidate_id' IS DISTINCT FROM expected_candidate_id THEN
            RAISE EXCEPTION 'invalid failure candidate identity' USING ERRCODE='23514';
        END IF;
        previous_link := (link->>'case_id') || ':' || (link->>'impact_id') || ':' ||
                         (link->>'basis');
    END LOOP;

    SELECT count(DISTINCT value->>'case_id') INTO linked_count
      FROM jsonb_array_elements(correlation->'candidates');
    SELECT count(*) INTO finding_count FROM jsonb_array_elements(report->'findings');
    SELECT COALESCE(jsonb_agg(f.value->>'case_id' ORDER BY f.value->>'case_id'),'[]'::jsonb)
      INTO unmatched FROM jsonb_array_elements(report->'findings') AS f(value)
      WHERE NOT EXISTS (SELECT 1 FROM jsonb_array_elements(correlation->'candidates') AS c(value)
                        WHERE c.value->>'case_id'=f.value->>'case_id');
    IF correlation->'coverage' IS DISTINCT FROM jsonb_build_object(
           'failing_cases',finding_count,
           'linked_failing_cases',linked_count,
           'declared_links',jsonb_array_length(p->'declared_links'),
           'unmatched_case_ids',unmatched,
           'scope','caller_declared_case_to_impact_links_only',
           'root_cause_coverage','NOT_ESTABLISHED') THEN
        RAISE EXCEPTION 'inconsistent failure correlation coverage' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value THEN
    RAISE EXCEPTION 'invalid failure correlation reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_failure_candidate_correlation() FROM PUBLIC;
CREATE TRIGGER failure_candidate_correlation_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_failure_candidate_correlation();
