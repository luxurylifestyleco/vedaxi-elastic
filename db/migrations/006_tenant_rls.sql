-- Elastic Web - 006_tenant_rls.sql
-- Tenant isolation for the assurance tables already created by 004.
-- Uses the existing app.tenant_id setting. Does not create a second schema.
-- Forward-only. Idempotent. No payment data.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.outcomes') IS NULL
       OR to_regclass('public.delegations') IS NULL
       OR to_regclass('public.evidence_records') IS NULL
       OR to_regclass('public.verification_results') IS NULL THEN
        RAISE EXCEPTION '004_outcome_assurance.sql must be applied before 006_tenant_rls.sql';
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elastic_runtime') THEN
        CREATE ROLE elastic_runtime NOINHERIT;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO elastic_runtime;
GRANT SELECT, INSERT ON public.outcomes, public.delegations, public.evidence_records, public.verification_results TO elastic_runtime;

ALTER TABLE public.outcomes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outcomes FORCE ROW LEVEL SECURITY;
ALTER TABLE public.delegations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.delegations FORCE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.evidence_records FORCE ROW LEVEL SECURITY;
ALTER TABLE public.verification_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.verification_results FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON public.outcomes;
CREATE POLICY tenant_isolation ON public.outcomes
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON public.delegations;
CREATE POLICY tenant_isolation ON public.delegations
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON public.evidence_records;
CREATE POLICY tenant_isolation ON public.evidence_records
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON public.verification_results;
CREATE POLICY tenant_isolation ON public.verification_results
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
