-- Reuse immutable artifacts/audit/RLS. Only migration administrators provision humans.
CREATE TABLE air_private.proposal_reviewers (
    login NAME PRIMARY KEY REFERENCES air_private.tenant_logins(login),
    reviewer_ref TEXT NOT NULL CHECK (reviewer_ref ~ '^[A-Za-z0-9_.:@-]{1,128}$'),
    enabled BOOLEAN NOT NULL DEFAULT TRUE
);
REVOKE ALL ON air_private.proposal_reviewers FROM PUBLIC;
CREATE FUNCTION air.current_reviewer() RETURNS TEXT
LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, air_private AS $$
DECLARE reviewer TEXT;
BEGIN
    PERFORM air.current_tenant();
    SELECT reviewer_ref INTO reviewer FROM air_private.proposal_reviewers
        WHERE login = session_user AND enabled;
    IF reviewer IS NULL THEN
        RAISE EXCEPTION 'explicit reviewer credentials required' USING ERRCODE = '42501';
    END IF;
    RETURN reviewer;
END $$;
REVOKE ALL ON FUNCTION air.current_reviewer() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION air.current_reviewer() TO air_runtime;

-- Unique indexes protect concurrent raw SQL as well as repository callers.
CREATE UNIQUE INDEX repair_one_successor ON air.artifacts
    (tenant_id, (payload::jsonb#>>'{supersedes,artifact_id}'))
    WHERE kind='repair_proposal' AND payload::jsonb->'supersedes' <> 'null'::jsonb;
CREATE UNIQUE INDEX repair_one_decision ON air.artifacts
    (tenant_id, (payload::jsonb#>>'{proposal,artifact_id}')) WHERE kind='repair_decision';

CREATE FUNCTION air.validate_repair_links() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog, air AS $$
DECLARE p JSONB; linked JSONB; linked_hash TEXT; parent JSONB; parent_hash TEXT;
    item JSONB; ref UUID; expected_keys TEXT[];
BEGIN
    IF NEW.kind NOT IN ('repair_proposal','repair_decision') THEN RETURN NEW; END IF;
    IF NEW.tenant_id <> air.current_tenant() THEN
        RAISE EXCEPTION 'unauthorized repair evidence' USING ERRCODE='42501';
    END IF;
    p := NEW.payload::jsonb;
    IF p->>'tenant_id' IS DISTINCT FROM NEW.tenant_id::text OR
       p->>'proposal_version' IS DISTINCT FROM 'air-repair-proposal-v1' OR
       jsonb_typeof(p->'revision') IS DISTINCT FROM 'number' OR
       (p->>'revision') !~ '^[1-9][0-9]{0,2}$' OR (p->>'revision')::int > 100 THEN
        RAISE EXCEPTION 'invalid repair evidence' USING ERRCODE='23514';
    END IF;
    IF NEW.kind='repair_proposal' THEN
        expected_keys := ARRAY['tenant_id','proposal_version','revision','supersedes','impact','change_evidence','registry','impact_item','description'];
        IF p - expected_keys <> '{}'::jsonb OR NOT p ?& expected_keys OR
           NEW.idempotency_key IS DISTINCT FROM NEW.content_hash OR
           jsonb_typeof(p->'description') IS DISTINCT FROM 'object' OR
           jsonb_typeof(p#>'{description,proposed_state}') IS DISTINCT FROM 'object' OR
           p#>'{description,proposed_state}' = '{}'::jsonb OR
           (p#>>'{description,change_type}') IS NULL OR
           (p#>>'{description,change_type}') NOT IN ('mapping_update','operation_update','configuration_update') OR
           (p#>>'{description,risk}') IS NULL OR (p#>>'{description,risk}') NOT IN ('low','medium','high') OR
           (p#>>'{description,generator}') IS NULL OR (p#>>'{description,generator}') NOT IN ('human','deterministic') OR
           jsonb_typeof(p#>'{description,rationale}') IS DISTINCT FROM 'string' OR
           length(btrim(p#>>'{description,rationale}')) NOT BETWEEN 1 AND 4096 OR
           jsonb_typeof(p#>'{description,generator_version}') IS DISTINCT FROM 'string' OR
           length(btrim(p#>>'{description,generator_version}')) NOT BETWEEN 1 AND 128 OR
           octet_length((p->'description')::text) > 131072 OR
           (p->'description') - ARRAY['change_type','proposed_state','rationale','risk','generator','generator_version'] <> '{}'::jsonb THEN
            RAISE EXCEPTION 'invalid proposal' USING ERRCODE='23514';
        END IF;
        SELECT payload::jsonb,content_hash INTO linked,linked_hash FROM air.artifacts
            WHERE tenant_id=NEW.tenant_id AND kind='contract_dependency_impact'
            AND artifact_id=(p#>>'{impact,artifact_id}')::uuid;
        IF linked IS NULL OR p->'impact' IS DISTINCT FROM jsonb_build_object('artifact_id',p#>>'{impact,artifact_id}','artifact_hash',linked_hash)
            OR p->'change_evidence' IS DISTINCT FROM linked->'change_evidence'
            OR p->'registry' IS DISTINCT FROM linked->'registry' THEN
            RAISE EXCEPTION 'invalid proposal evidence' USING ERRCODE='23514';
        END IF;
        SELECT value INTO item FROM jsonb_array_elements((linked#>'{analysis,impacts}') ||
            COALESCE(linked#>'{analysis,downstream_impacts}','[]'::jsonb))
            WHERE value=p->'impact_item' LIMIT 1;
        IF item IS NULL THEN RAISE EXCEPTION 'invalid impact target' USING ERRCODE='23514'; END IF;
        IF p->'supersedes'='null'::jsonb THEN
            IF p->>'revision' <> '1' THEN RAISE EXCEPTION 'invalid revision' USING ERRCODE='23514'; END IF;
        ELSE
            ref := (p#>>'{supersedes,artifact_id}')::uuid;
            PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || ':' || ref::text,714208316));
            SELECT payload::jsonb,content_hash INTO parent,parent_hash FROM air.artifacts
                WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal' AND artifact_id=ref;
            IF parent IS NULL OR p->'supersedes' IS DISTINCT FROM jsonb_build_object('artifact_id',ref::text,'artifact_hash',parent_hash)
                OR (p->>'revision')::int <> (parent->>'revision')::int+1
                OR p#>'{impact_item,dependency,integration_id}' IS DISTINCT FROM parent#>'{impact_item,dependency,integration_id}'
                OR p#>'{impact_item,dependency,mapping_id}' IS DISTINCT FROM parent#>'{impact_item,dependency,mapping_id}' THEN
                RAISE EXCEPTION 'invalid revision' USING ERRCODE='23514';
            END IF;
        END IF;
    ELSE
        expected_keys := ARRAY['tenant_id','proposal_version','revision','proposal','decision','reviewer','impact','change_evidence'];
        ref := (p#>>'{proposal,artifact_id}')::uuid;
        PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text || ':' || ref::text,714208316));
        SELECT payload::jsonb,content_hash INTO linked,linked_hash FROM air.artifacts
            WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal' AND artifact_id=ref;
        IF linked IS NULL OR p - expected_keys <> '{}'::jsonb OR NOT p ?& expected_keys OR
           NEW.idempotency_key IS DISTINCT FROM ref::text OR
           p->'proposal' IS DISTINCT FROM jsonb_build_object('artifact_id',ref::text,'artifact_hash',linked_hash) OR
           p->'revision' IS DISTINCT FROM linked->'revision' OR
           p->'impact' IS DISTINCT FROM linked->'impact' OR
           p->'change_evidence' IS DISTINCT FROM linked->'change_evidence' OR
           p->>'decision' IS NULL OR p->>'decision' NOT IN ('APPROVED','REJECTED') OR
           p->>'reviewer' IS DISTINCT FROM air.current_reviewer() OR
           EXISTS(SELECT 1 FROM air.artifacts WHERE tenant_id=NEW.tenant_id AND kind='repair_proposal'
               AND payload::jsonb#>>'{supersedes,artifact_id}'=ref::text) THEN
            RAISE EXCEPTION 'invalid or stale decision' USING ERRCODE='23514';
        END IF;
    END IF;
    RETURN NEW;
EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'invalid repair reference' USING ERRCODE='23514';
END $$;
REVOKE ALL ON FUNCTION air.validate_repair_links() FROM PUBLIC;
CREATE TRIGGER repair_evidence_links BEFORE INSERT ON air.artifacts
    FOR EACH ROW EXECUTE FUNCTION air.validate_repair_links();
