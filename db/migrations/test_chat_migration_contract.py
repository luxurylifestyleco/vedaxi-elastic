from pathlib import Path


MIGRATION = Path(__file__).with_name("007_chat_conversation_tasks.sql")


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def executable_sql() -> str:
    return "\n".join(line for line in sql().splitlines() if not line.lstrip().startswith("--"))


def test_chat_schema_is_additive_transactional_and_does_not_create_roles():
    text = sql()
    executable = executable_sql()
    assert text.startswith("-- elastic web - 007_chat_conversation_tasks.sql")
    assert "begin;" in text and "commit;" in text
    assert "create table if not exists public.chat_sessions" in text
    assert "create table if not exists public.conversation_messages" in text
    assert "create table if not exists public.a2a_tasks" in text
    assert "drop table" not in executable
    assert "create role" not in executable
    assert "004_outcome_assurance.sql must be applied before" in text
    assert "006_tenant_rls.sql must be applied before" in text


def test_chat_schema_has_tenant_ownership_and_cross_table_keys():
    text = sql()
    for table in ("chat_sessions", "conversation_messages", "a2a_tasks"):
        definition = text.split(f"create table if not exists public.{table}", 1)[1]
        assert "tenant_id text not null" in definition
    assert "foreign key (tenant_id, session_id, context_id, principal_id)" in text
    assert "foreign key (tenant_id, task_id)" in text
    assert "references public.chat_sessions(tenant_id, session_id, context_id, principal_id)" in text
    assert "references public.a2a_tasks(tenant_id, task_id)" in text
    assert "a2a_tasks_message_fk" in text


def test_chat_schema_preserves_session_message_task_correlation_and_lifecycle():
    text = sql()
    for field in ("session_id", "context_id", "message_id", "task_id"):
        assert f"{field} text" in text
    for field in ("intent_id", "trace_id", "outcome_id", "evidence_id", "verification_id"):
        assert f"{field} text" in text
    for field in ("authenticated_at", "consented_scopes", "policy_epoch", "authorization_decision_id"):
        assert field in text
    for field in ("issued_at", "expires_at", "revoked_at", "cancel_state", "cancellation_requested_at", "canceled_at"):
        assert field in text
    assert "message_id text primary key" in text
    assert "unique (tenant_id, message_id)" in text
    assert "a2a_tasks_cancel_state_check" in text
    assert "a2a_tasks_state_check" in text
    assert "chat_sessions_window_check" in text


def test_chat_schema_has_durable_idempotency_and_mutability_policy():
    text = sql()
    assert "unique (tenant_id, message_id)" in text
    assert "chat_sessions_session_context_principal_key" in text
    assert "conversation_messages_session_context_principal_fk" in text
    assert "a2a_tasks_message_fk" in text
    assert "chat_reject_immutable_update" in text
    assert "chat_sessions_immutable_fields" in text
    assert "conversation_messages_immutable_fields" in text
    assert "a2a_tasks_immutable_fields" in text
    assert "to_jsonb(new)" in text
    assert "to_jsonb(old)" in text
    assert "identity and content fields are immutable" in text
    assert "identity and correlation fields are immutable" in text
    assert "identity, consent, authorization, and issuance are immutable" in text
    assert "task_id may be linked once after task creation" in text


def test_chat_schema_has_restart_safe_lifecycle_triggers_and_forward_only_guards():
    executable = executable_sql()
    assert "chat_touch_updated_at" in executable
    assert "chat_sessions_touch_updated_at" in executable
    assert "a2a_tasks_touch_updated_at" in executable
    assert "alter table public.chat_sessions add column if not exists authenticated_at" in executable
    assert "alter table public.chat_sessions add column if not exists principal_kind" in executable
    assert "alter table public.a2a_tasks add column if not exists intent_id" in executable
    assert "alter table public.a2a_tasks add column if not exists trace_id" in executable
    assert "alter table public.conversation_messages add column if not exists principal_id" in executable
    assert "drop table" not in executable
    assert "drop policy" in executable


def test_chat_schema_has_tenant_rls_and_required_indexes():
    executable = executable_sql()
    for table in ("chat_sessions", "conversation_messages", "a2a_tasks"):
        assert f"alter table public.{table} enable row level security" in executable
        assert f"alter table public.{table} force row level security" in executable
    assert executable.count("create policy tenant_isolation") == 3
    assert "current_setting('app.tenant_id', true)" in executable
    for index in (
        "idx_chat_sessions_tenant_principal",
        "idx_chat_sessions_expiry",
        "idx_conversation_messages_context",
        "idx_a2a_tasks_context_state",
        "idx_a2a_tasks_session",
    ):
        assert index in executable


def test_chat_schema_has_no_trailing_table_constraint_comma():
    assert ",\n);" not in executable_sql()
