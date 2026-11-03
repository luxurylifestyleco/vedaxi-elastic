from pathlib import Path


MIGRATION = Path(__file__).with_name("005_outcome_assurance_hardening.sql")
BASE_MIGRATION = Path(__file__).with_name("004_outcome_assurance.sql")


def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8").lower()


def base_sql() -> str:
    return BASE_MIGRATION.read_text(encoding="utf-8").lower()


def executable_sql() -> str:
    return "\n".join(line for line in sql().splitlines() if not line.lstrip().startswith("--"))


def test_migration_is_forward_only_and_transactional():
    text = sql()
    executable = executable_sql()
    assert text.startswith("-- elastic web - 005_outcome_assurance_hardening.sql")
    assert "begin;" in text
    assert "commit;" in text
    assert "drop table" not in executable
    assert "drop constraint" not in executable
    assert "create role" not in executable
    assert "enable row level security" not in executable


def test_migration_requires_the_base_assurance_schema():
    text = sql()
    assert "004_outcome_assurance.sql must be applied before" in text
    for table in ("outcomes", "delegations", "evidence_records", "verification_results"):
        assert f"to_regclass('public.{table}')" in text


def test_corrections_are_bound_to_the_same_tenant():
    text = sql()
    assert "evidence_correction_same_tenant_fk" in text
    assert "foreign key (tenant_id, correction_of_evidence_id)" in text
    assert "references public.evidence_records (tenant_id, evidence_id)" in text


def test_json_shape_checks_cover_python_contract_collections():
    text = sql()
    required_checks = (
        "outcomes_required_capabilities_array_check",
        "delegations_capabilities_array_check",
        "delegations_resource_scopes_array_check",
        "delegations_constraints_object_check",
        "outcomes_policy_objects_check",
    )
    for check in required_checks:
        assert check in text
    assert "jsonb_typeof(required_capabilities) = 'array'" in text
    assert "jsonb_array_length(capabilities) > 0" in text
    assert "jsonb_array_length(resource_scopes) > 0" in text
    assert "jsonb_typeof(intent) = 'object'" in text


def test_new_constraints_are_not_validated_against_existing_rows_implicitly():
    text = sql()
    assert text.count("not valid") >= 7


def test_retention_metadata_is_required_on_evidence_records():
    text = base_sql()
    evidence_definition = text.split("create table if not exists evidence_records", 1)[1].split(
        "create table if not exists verification_results", 1
    )[0]
    assert "retention_policy text not null" in evidence_definition
    assert "privacy_classification text not null" in evidence_definition
    assert "recorded_at timestamptz not null default now()" in evidence_definition


def test_retention_and_expiry_have_evaluable_timestamp_shapes():
    text = base_sql()
    delegation_definition = text.split("create table if not exists delegations", 1)[1].split(
        "create table if not exists evidence_records", 1
    )[0]
    evidence_definition = text.split("create table if not exists evidence_records", 1)[1].split(
        "create table if not exists verification_results", 1
    )[0]
    assert "issued_at timestamptz not null" in delegation_definition
    assert "expires_at timestamptz not null" in delegation_definition
    assert "constraint delegations_window_check check (expires_at > issued_at)" in delegation_definition
    assert "observed_at timestamptz not null" in evidence_definition
    assert "received_at timestamptz not null" in evidence_definition
    assert "recorded_at timestamptz not null default now()" in evidence_definition


def test_rls_lives_in_the_following_migration_not_in_005():
    following = Path(__file__).with_name("006_tenant_rls.sql").read_text(encoding="utf-8").lower()
    executable = "\n".join(line for line in following.splitlines() if not line.lstrip().startswith("--"))
    assert "enable row level security" in executable
    assert "force row level security" in executable
    assert "current_setting('app.tenant_id', true)" in executable
    assert "elastic_runtime" in executable
    assert "delete from evidence_records" not in executable
    assert "enable row level security" not in executable_sql()


def test_retention_policy_is_metadata_only_until_an_explicit_enforcement_contract_exists():
    text = base_sql()
    assert "retention_policy text not null" in text
    assert "delete from evidence_records" not in executable_sql_for(text)


def executable_sql_for(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
