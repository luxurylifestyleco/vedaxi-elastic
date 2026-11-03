-- Elastic Web - 005_outcome_assurance_hardening.sql
-- Forward-only local hardening for the outcome assurance boundary.
--
-- This migration deliberately does not create roles, configure RLS, or define
-- tenant identity. NOT VALID constraints protect future writes while leaving
-- pre-existing rows for a separately approved data-quality/tenant review.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.outcomes') IS NULL
       OR to_regclass('public.delegations') IS NULL
       OR to_regclass('public.evidence_records') IS NULL
       OR to_regclass('public.verification_results') IS NULL THEN
        RAISE EXCEPTION '004_outcome_assurance.sql must be applied before 005_outcome_assurance_hardening.sql';
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'evidence_correction_same_tenant_fk'
          AND conrelid = 'public.evidence_records'::regclass
    ) THEN
        ALTER TABLE public.evidence_records
            ADD CONSTRAINT evidence_correction_same_tenant_fk
            FOREIGN KEY (tenant_id, correction_of_evidence_id)
            REFERENCES public.evidence_records (tenant_id, evidence_id)
            NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'outcomes_required_capabilities_array_check'
          AND conrelid = 'public.outcomes'::regclass
    ) THEN
        ALTER TABLE public.outcomes
            ADD CONSTRAINT outcomes_required_capabilities_array_check
            CHECK (jsonb_typeof(required_capabilities) = 'array')
            NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'delegations_capabilities_array_check'
          AND conrelid = 'public.delegations'::regclass
    ) THEN
        ALTER TABLE public.delegations
            ADD CONSTRAINT delegations_capabilities_array_check
            CHECK (jsonb_typeof(capabilities) = 'array' AND jsonb_array_length(capabilities) > 0)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'delegations_resource_scopes_array_check'
          AND conrelid = 'public.delegations'::regclass
    ) THEN
        ALTER TABLE public.delegations
            ADD CONSTRAINT delegations_resource_scopes_array_check
            CHECK (jsonb_typeof(resource_scopes) = 'array' AND jsonb_array_length(resource_scopes) > 0)
            NOT VALID;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'delegations_constraints_object_check'
          AND conrelid = 'public.delegations'::regclass
    ) THEN
        ALTER TABLE public.delegations
            ADD CONSTRAINT delegations_constraints_object_check
            CHECK (jsonb_typeof(constraints) = 'object')
            NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'outcomes_policy_objects_check'
          AND conrelid = 'public.outcomes'::regclass
    ) THEN
        ALTER TABLE public.outcomes
            ADD CONSTRAINT outcomes_policy_objects_check
            CHECK (
                jsonb_typeof(intent) = 'object'
                AND jsonb_typeof(desired_state) = 'object'
                AND jsonb_typeof(constraints) = 'object'
                AND jsonb_typeof(approval_policy) = 'object'
                AND jsonb_typeof(verification_policy) = 'object'
                AND jsonb_typeof(evidence_collection_policy) = 'object'
                AND jsonb_typeof(recovery_policy) = 'object'
            )
            NOT VALID;
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'delegations_revocation_window_check'
          AND conrelid = 'public.delegations'::regclass
    ) THEN
        ALTER TABLE public.delegations
            ADD CONSTRAINT delegations_revocation_window_check
            CHECK (revoked_at IS NULL OR revoked_at >= issued_at)
            NOT VALID;
    END IF;
END
$$;

COMMIT;
