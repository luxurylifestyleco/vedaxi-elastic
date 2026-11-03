-- Elastic Web - 004_outcome_assurance.sql
-- Additive outcome/delegation/evidence boundary.
-- Telemetry remains operational observability; these are authoritative records.
-- Large artifacts stay outside PostgreSQL. No anonymous tenant default exists.

CREATE TABLE IF NOT EXISTS outcomes (
    outcome_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    schema_version TEXT NOT NULL DEFAULT '1.0',
    principal_id TEXT NOT NULL,
    originating_agent_id TEXT NOT NULL,
    delegated_authority_reference TEXT,
    intent JSONB NOT NULL,
    desired_state JSONB NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    deadline TIMESTAMPTZ,
    required_capabilities JSONB NOT NULL DEFAULT '[]'::jsonb,
    execution_plan_reference TEXT,
    approval_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    verification_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    completion_criteria JSONB NOT NULL,
    evidence_collection_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    recovery_policy JSONB NOT NULL DEFAULT '{}'::jsonb,
    current_status TEXT NOT NULL DEFAULT 'CREATED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT outcomes_status_check CHECK (current_status IN ('CREATED','VALIDATING','AUTHORIZATION_REQUIRED','AUTHORIZED','PLANNING','EXECUTING','PARTIALLY_COMPLETED','RECOVERY_REQUIRED','VERIFYING','COMPLETED','FAILED','CANCELLED','EXPIRED','DISPUTED')),
    CONSTRAINT outcomes_criteria_array_check CHECK (jsonb_typeof(completion_criteria) = 'array' AND jsonb_array_length(completion_criteria) > 0),
    UNIQUE (tenant_id, outcome_id)
);

CREATE TABLE IF NOT EXISTS delegations (
    delegation_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    delegator_id TEXT NOT NULL,
    delegatee_id TEXT NOT NULL,
    parent_delegation_id TEXT REFERENCES delegations(delegation_id),
    capabilities JSONB NOT NULL,
    resource_scopes JSONB NOT NULL,
    constraints JSONB NOT NULL DEFAULT '{}'::jsonb,
    further_delegation_allowed BOOLEAN NOT NULL DEFAULT false,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    authorization_proof TEXT NOT NULL,
    CONSTRAINT delegations_window_check CHECK (expires_at > issued_at),
    UNIQUE (tenant_id, delegation_id),
    CONSTRAINT delegations_parent_same_tenant_fk FOREIGN KEY (tenant_id, parent_delegation_id)
        REFERENCES delegations(tenant_id, delegation_id)
);

CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL REFERENCES outcomes(outcome_id),
    execution_id TEXT NOT NULL,
    evidence_type TEXT NOT NULL,
    claim TEXT NOT NULL,
    subject TEXT NOT NULL,
    issuer TEXT NOT NULL,
    source TEXT NOT NULL,
    producer TEXT NOT NULL,
    issued_at TIMESTAMPTZ,
    occurred_at TIMESTAMPTZ,
    observed_at TIMESTAMPTZ NOT NULL,
    received_at TIMESTAMPTZ NOT NULL,
    artifact_reference TEXT,
    content_digest TEXT,
    signature_reference TEXT,
    protocol_origin TEXT NOT NULL,
    related_event_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    related_evidence_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    correction_of_evidence_id TEXT REFERENCES evidence_records(evidence_id),
    delegation_reference TEXT,
    verification_status TEXT NOT NULL DEFAULT 'PENDING',
    assurance_level TEXT,
    privacy_classification TEXT NOT NULL,
    retention_policy TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT evidence_type_check CHECK (evidence_type IN ('execution_event','agent_claim','provider_receipt','attestation','verification_result')),
    CONSTRAINT evidence_status_check CHECK (verification_status IN ('VERIFIED','FAILED','INSUFFICIENT','PENDING','CONFLICTING','EXPIRED','REVOKED')),
    CONSTRAINT evidence_event_ids_array_check CHECK (jsonb_typeof(related_event_ids) = 'array'),
    CONSTRAINT evidence_related_ids_array_check CHECK (jsonb_typeof(related_evidence_ids) = 'array'),
    UNIQUE (tenant_id, evidence_id),
    CONSTRAINT evidence_outcome_same_tenant_fk FOREIGN KEY (tenant_id, outcome_id)
        REFERENCES outcomes(tenant_id, outcome_id)
);

CREATE TABLE IF NOT EXISTS verification_results (
    verification_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    outcome_id TEXT NOT NULL REFERENCES outcomes(outcome_id),
    execution_id TEXT NOT NULL,
    status TEXT NOT NULL,
    checked JSONB NOT NULL,
    policy_reference TEXT NOT NULL,
    evidence_ids JSONB NOT NULL,
    passed_checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    failed_checks JSONB NOT NULL DEFAULT '[]'::jsonb,
    verified_at TIMESTAMPTZ NOT NULL,
    verifier_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT verification_status_check CHECK (status IN ('VERIFIED','FAILED','INSUFFICIENT','PENDING','CONFLICTING','EXPIRED','REVOKED')),
    CONSTRAINT verification_checked_array_check CHECK (jsonb_typeof(checked) = 'array' AND jsonb_array_length(checked) > 0),
    CONSTRAINT verification_evidence_ids_array_check CHECK (jsonb_typeof(evidence_ids) = 'array' AND jsonb_array_length(evidence_ids) > 0),
    UNIQUE (tenant_id, verification_id),
    CONSTRAINT verification_outcome_same_tenant_fk FOREIGN KEY (tenant_id, outcome_id)
        REFERENCES outcomes(tenant_id, outcome_id)
);

CREATE INDEX IF NOT EXISTS idx_outcomes_tenant_status ON outcomes(tenant_id, current_status);
CREATE INDEX IF NOT EXISTS idx_outcomes_principal ON outcomes(tenant_id, principal_id);
CREATE INDEX IF NOT EXISTS idx_delegations_delegatee ON delegations(tenant_id, delegatee_id);
CREATE INDEX IF NOT EXISTS idx_evidence_outcome ON evidence_records(tenant_id, outcome_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_evidence_execution ON evidence_records(tenant_id, execution_id);
CREATE INDEX IF NOT EXISTS idx_verification_outcome ON verification_results(tenant_id, outcome_id, verified_at);

CREATE OR REPLACE FUNCTION reject_assurance_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'assurance records are append-only; write a correction or new result';
END;
$$;

DROP TRIGGER IF EXISTS evidence_records_no_update ON evidence_records;
CREATE TRIGGER evidence_records_no_update
    BEFORE UPDATE OR DELETE ON evidence_records
    FOR EACH ROW EXECUTE FUNCTION reject_assurance_mutation();

DROP TRIGGER IF EXISTS verification_results_no_update ON verification_results;
CREATE TRIGGER verification_results_no_update
    BEFORE UPDATE OR DELETE ON verification_results
    FOR EACH ROW EXECUTE FUNCTION reject_assurance_mutation();
