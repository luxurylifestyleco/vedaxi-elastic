-- Elastic Web - 007_chat_conversation_tasks.sql
-- Additive durable boundary for authenticated chat sessions and A2A task state.
-- Requires 004_outcome_assurance.sql and 006_tenant_rls.sql.

BEGIN;

DO $$
BEGIN
    IF to_regclass('public.outcomes') IS NULL
       OR to_regclass('public.evidence_records') IS NULL
       OR to_regclass('public.verification_results') IS NULL THEN
        RAISE EXCEPTION '004_outcome_assurance.sql must be applied before 007_chat_conversation_tasks.sql';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'elastic_runtime') THEN
        RAISE EXCEPTION '006_tenant_rls.sql must be applied before 007_chat_conversation_tasks.sql';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.chat_sessions (
    session_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    principal_kind TEXT NOT NULL,
    consent_id TEXT NOT NULL,
    scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    authenticated_at TIMESTAMPTZ,
    consented_scopes JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_epoch INTEGER NOT NULL DEFAULT 1,
    authorization_decision_id TEXT,
    context_id TEXT NOT NULL,
    issued_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    revoked_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chat_sessions_scope_array_check CHECK (jsonb_typeof(scopes) = 'array'),
    CONSTRAINT chat_sessions_consented_scope_array_check CHECK (jsonb_typeof(consented_scopes) = 'array'),
    CONSTRAINT chat_sessions_policy_epoch_check CHECK (policy_epoch > 0),
    CONSTRAINT chat_sessions_principal_kind_check CHECK (principal_kind IN ('human', 'agent')),
    CONSTRAINT chat_sessions_window_check CHECK (expires_at > issued_at),
    CONSTRAINT chat_sessions_revocation_window_check CHECK (revoked_at IS NULL OR revoked_at >= issued_at),
    UNIQUE (tenant_id, session_id),
    UNIQUE (tenant_id, context_id),
    UNIQUE (tenant_id, session_id, context_id, principal_id)
);

CREATE TABLE IF NOT EXISTS public.a2a_tasks (
    task_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    message_id TEXT,
    intent_id TEXT,
    trace_id TEXT,
    outcome_id TEXT,
    evidence_id TEXT,
    verification_id TEXT,
    state TEXT NOT NULL DEFAULT 'submitted',
    cancel_state TEXT NOT NULL DEFAULT 'not_requested',
    cancellation_requested_at TIMESTAMPTZ,
    canceled_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT a2a_tasks_state_check CHECK (state IN ('submitted', 'working', 'input-required', 'completed', 'failed', 'canceled')),
    CONSTRAINT a2a_tasks_cancel_state_check CHECK (cancel_state IN ('not_requested', 'requested', 'canceled', 'rejected')),
    CONSTRAINT a2a_tasks_cancel_window_check CHECK (canceled_at IS NULL OR cancellation_requested_at IS NOT NULL),
    UNIQUE (tenant_id, task_id),
    CONSTRAINT a2a_tasks_session_context_principal_fk FOREIGN KEY (tenant_id, session_id, context_id, principal_id)
        REFERENCES public.chat_sessions(tenant_id, session_id, context_id, principal_id)
    -- message linkage is added after conversation_messages exists below.
);

CREATE TABLE IF NOT EXISTS public.conversation_messages (
    message_id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    context_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    role TEXT NOT NULL,
    parts JSONB NOT NULL,
    task_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT conversation_messages_role_check CHECK (role IN ('user', 'agent')),
    CONSTRAINT conversation_messages_parts_array_check CHECK (jsonb_typeof(parts) = 'array' AND jsonb_array_length(parts) > 0),
    UNIQUE (tenant_id, message_id),
    CONSTRAINT conversation_messages_session_context_principal_fk FOREIGN KEY (tenant_id, session_id, context_id, principal_id)
        REFERENCES public.chat_sessions(tenant_id, session_id, context_id, principal_id),
    CONSTRAINT conversation_messages_task_same_tenant_fk FOREIGN KEY (tenant_id, task_id)
        REFERENCES public.a2a_tasks(tenant_id, task_id)
        DEFERRABLE INITIALLY DEFERRED
);

-- Forward-compatible columns for databases where 007 was partially applied.
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS principal_kind TEXT NOT NULL DEFAULT 'agent';
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS authenticated_at TIMESTAMPTZ;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS consented_scopes JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS policy_epoch INTEGER NOT NULL DEFAULT 1;
ALTER TABLE public.chat_sessions ADD COLUMN IF NOT EXISTS authorization_decision_id TEXT;
ALTER TABLE public.a2a_tasks ADD COLUMN IF NOT EXISTS intent_id TEXT;
ALTER TABLE public.a2a_tasks ADD COLUMN IF NOT EXISTS trace_id TEXT;
ALTER TABLE public.a2a_tasks ADD COLUMN IF NOT EXISTS outcome_id TEXT;
ALTER TABLE public.a2a_tasks ADD COLUMN IF NOT EXISTS evidence_id TEXT;
ALTER TABLE public.a2a_tasks ADD COLUMN IF NOT EXISTS verification_id TEXT;
ALTER TABLE public.conversation_messages ADD COLUMN IF NOT EXISTS principal_id TEXT;

-- Existing rows cannot be safely assigned a principal; fail closed until backfilled by the owner.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.conversation_messages WHERE principal_id IS NULL) THEN
        RAISE EXCEPTION '007 requires a principal_id backfill for existing conversation_messages rows';
    END IF;
    ALTER TABLE public.conversation_messages ALTER COLUMN principal_id SET NOT NULL;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_sessions_consented_scope_array_check') THEN
        ALTER TABLE public.chat_sessions ADD CONSTRAINT chat_sessions_consented_scope_array_check
            CHECK (jsonb_typeof(consented_scopes) = 'array');
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_sessions_policy_epoch_check') THEN
        ALTER TABLE public.chat_sessions ADD CONSTRAINT chat_sessions_policy_epoch_check
            CHECK (policy_epoch > 0);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'chat_sessions_session_context_principal_key') THEN
        ALTER TABLE public.chat_sessions ADD CONSTRAINT chat_sessions_session_context_principal_key
            UNIQUE (tenant_id, session_id, context_id, principal_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'conversation_messages_session_context_principal_fk') THEN
        ALTER TABLE public.conversation_messages ADD CONSTRAINT conversation_messages_session_context_principal_fk
            FOREIGN KEY (tenant_id, session_id, context_id, principal_id)
            REFERENCES public.chat_sessions(tenant_id, session_id, context_id, principal_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'a2a_tasks_session_context_principal_fk') THEN
        ALTER TABLE public.a2a_tasks ADD CONSTRAINT a2a_tasks_session_context_principal_fk
            FOREIGN KEY (tenant_id, session_id, context_id, principal_id)
            REFERENCES public.chat_sessions(tenant_id, session_id, context_id, principal_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'a2a_tasks_message_fk') THEN
        ALTER TABLE public.a2a_tasks ADD CONSTRAINT a2a_tasks_message_fk
            FOREIGN KEY (tenant_id, message_id)
            REFERENCES public.conversation_messages(tenant_id, message_id)
            DEFERRABLE INITIALLY DEFERRED;
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.chat_touch_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'chat_sessions_touch_updated_at') THEN
        CREATE TRIGGER chat_sessions_touch_updated_at
            BEFORE UPDATE ON public.chat_sessions
            FOR EACH ROW EXECUTE FUNCTION public.chat_touch_updated_at();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'a2a_tasks_touch_updated_at') THEN
        CREATE TRIGGER a2a_tasks_touch_updated_at
            BEFORE UPDATE ON public.a2a_tasks
            FOR EACH ROW EXECUTE FUNCTION public.chat_touch_updated_at();
    END IF;
END
$$;

CREATE OR REPLACE FUNCTION public.chat_reject_immutable_update()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_TABLE_NAME = 'chat_sessions' AND (
        to_jsonb(NEW) - ARRAY['revoked_at', 'updated_at', 'created_at']
    ) IS DISTINCT FROM (
        to_jsonb(OLD) - ARRAY['revoked_at', 'updated_at', 'created_at']
    ) THEN
        RAISE EXCEPTION 'chat session identity and issuance fields are immutable';
    ELSIF TG_TABLE_NAME = 'conversation_messages' AND (
        to_jsonb(NEW) - ARRAY['task_id']
    ) IS DISTINCT FROM (
        to_jsonb(OLD) - ARRAY['task_id']
    ) THEN
        RAISE EXCEPTION 'conversation message identity and content fields are immutable';
    ELSIF TG_TABLE_NAME = 'a2a_tasks' AND (
        to_jsonb(NEW) - ARRAY[
            'state', 'cancel_state', 'cancellation_requested_at', 'canceled_at',
            'expires_at', 'updated_at', 'outcome_id', 'evidence_id', 'verification_id'
        ]
    ) IS DISTINCT FROM (
        to_jsonb(OLD) - ARRAY[
            'state', 'cancel_state', 'cancellation_requested_at', 'canceled_at',
            'expires_at', 'updated_at', 'outcome_id', 'evidence_id', 'verification_id'
        ]
    ) THEN
        RAISE EXCEPTION 'a2a task identity and correlation fields are immutable';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'chat_sessions_immutable_fields') THEN
        CREATE TRIGGER chat_sessions_immutable_fields
            BEFORE UPDATE ON public.chat_sessions
            FOR EACH ROW EXECUTE FUNCTION public.chat_reject_immutable_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'conversation_messages_immutable_fields') THEN
        CREATE TRIGGER conversation_messages_immutable_fields
            BEFORE UPDATE ON public.conversation_messages
            FOR EACH ROW EXECUTE FUNCTION public.chat_reject_immutable_update();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'a2a_tasks_immutable_fields') THEN
        CREATE TRIGGER a2a_tasks_immutable_fields
            BEFORE UPDATE ON public.a2a_tasks
            FOR EACH ROW EXECUTE FUNCTION public.chat_reject_immutable_update();
    END IF;
END
$$;

COMMENT ON TABLE public.chat_sessions IS 'Identity, consent, authorization, and issuance are immutable; only revocation and updated_at may change.';
COMMENT ON TABLE public.conversation_messages IS 'Message identity and parts are immutable; task_id may be linked once after task creation.';
COMMENT ON TABLE public.a2a_tasks IS 'Task identity and initial correlation are immutable; state, cancellation, and assurance references may advance.';

CREATE INDEX IF NOT EXISTS idx_chat_sessions_tenant_principal
    ON public.chat_sessions(tenant_id, principal_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_expiry
    ON public.chat_sessions(tenant_id, expires_at);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_context
    ON public.conversation_messages(tenant_id, context_id, created_at);
CREATE INDEX IF NOT EXISTS idx_conversation_messages_task
    ON public.conversation_messages(tenant_id, task_id);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_context_state
    ON public.a2a_tasks(tenant_id, context_id, state, updated_at);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_session
    ON public.a2a_tasks(tenant_id, session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_a2a_tasks_expiry
    ON public.a2a_tasks(tenant_id, expires_at);

GRANT SELECT, INSERT, UPDATE ON public.chat_sessions, public.conversation_messages, public.a2a_tasks TO elastic_runtime;

ALTER TABLE public.chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.chat_sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversation_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE public.a2a_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.a2a_tasks FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON public.chat_sessions;
CREATE POLICY tenant_isolation ON public.chat_sessions
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON public.conversation_messages;
CREATE POLICY tenant_isolation ON public.conversation_messages
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

DROP POLICY IF EXISTS tenant_isolation ON public.a2a_tasks;
CREATE POLICY tenant_isolation ON public.a2a_tasks
    FOR ALL TO elastic_runtime
    USING (tenant_id = current_setting('app.tenant_id', true))
    WITH CHECK (tenant_id = current_setting('app.tenant_id', true));

COMMIT;
