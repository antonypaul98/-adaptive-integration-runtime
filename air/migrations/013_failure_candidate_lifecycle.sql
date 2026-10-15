-- Close the exact lifecycle gap for persisted AIR-23 candidate correlations.
-- A valid impact with equivalent analysis is insufficient: it must be the exact
-- impact already bound to the investigation's replay and sandbox evidence.
CREATE FUNCTION air.validate_failure_candidate_lifecycle() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE
    candidate JSONB; investigation JSONB; verification JSONB; sandbox JSONB; impact JSONB;
    investigation_id UUID; verification_id UUID; sandbox_id UUID; impact_id UUID;
    verification_hash TEXT; sandbox_hash TEXT; impact_hash TEXT;
BEGIN
    IF NEW.kind <> 'failure_candidate_correlation' THEN RETURN NEW; END IF;
    candidate := NEW.payload::jsonb;
    investigation_id := (candidate#>>'{investigation,artifact_id}')::uuid;
    impact_id := (candidate#>>'{impact,artifact_id}')::uuid;

    SELECT payload::jsonb INTO investigation
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='failure_investigation' AND artifact_id=investigation_id;
    verification_id := (investigation#>>'{verification,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO verification,verification_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='replay_verification' AND artifact_id=verification_id;
    sandbox_id := (verification#>>'{sandbox,artifact_id}')::uuid;
    SELECT payload::jsonb,content_hash INTO sandbox,sandbox_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='sandbox_evaluation' AND artifact_id=sandbox_id;
    SELECT payload::jsonb,content_hash INTO impact,impact_hash
      FROM air.artifacts WHERE tenant_id=NEW.tenant_id
        AND kind='contract_dependency_impact' AND artifact_id=impact_id;

    IF investigation IS NULL OR verification IS NULL OR sandbox IS NULL OR impact IS NULL OR
       investigation->'verification' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',verification_id::text,'artifact_hash',verification_hash) OR
       verification->'sandbox' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',sandbox_id::text,'artifact_hash',sandbox_hash) OR
       verification->'impact' IS DISTINCT FROM jsonb_build_object(
           'artifact_id',impact_id::text,'artifact_hash',impact_hash) OR
       sandbox->'impact' IS DISTINCT FROM verification->'impact' OR
       verification->'change_evidence' IS DISTINCT FROM impact->'change_evidence' OR
       sandbox->'change_evidence' IS DISTINCT FROM impact->'change_evidence' OR
       verification->>'fixture_hash' IS DISTINCT FROM
           ((investigation->>'report_payload')::jsonb#>>'{source,fixture_hash}') THEN
        RAISE EXCEPTION 'unbound failure candidate lifecycle' USING ERRCODE='23514';
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR invalid_parameter_value OR null_value_not_allowed THEN
    RAISE EXCEPTION 'invalid failure candidate lifecycle' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_failure_candidate_lifecycle() FROM PUBLIC;
CREATE TRIGGER failure_candidate_lifecycle_integrity BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_failure_candidate_lifecycle();
