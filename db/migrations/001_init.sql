-- ============================================================================
-- Elastic Web — 001_init.sql
-- Initial schema: capabilities, intent_examples, recipes, recipe_versions,
-- execution_traces, execution_steps, evaluations, benchmark_runs.
--
-- Design notes:
--   * JSONB is used generously for evolving Elastic structures. We deliberately
--     do NOT over-normalize: flexible payloads live in JSONB columns and are
--     indexed with GIN where they need to be queried.
--   * pgvector: the 'vector' extension is OPTIONAL. If it is installed we
--     enable it (and the migration is tolerant of it being absent). Embeddings
--     are stored as JSONB arrays so the schema works with or without pgvector.
--   * Idempotent: safe to run multiple times (CREATE TABLE IF NOT EXISTS).
-- ===========================================================================

-- ---------------------------------------------------------------------------
-- Optional pgvector extension (tolerant — does not fail if unavailable).
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS vector;
EXCEPTION
    WHEN OTHERS THEN
        RAISE NOTICE 'pgvector extension not available (%): %', SQLSTATE, SQLERRM;
        RAISE NOTICE 'Embeddings will be stored as JSONB arrays instead of vector type.';
END
$$;

-- ---------------------------------------------------------------------------
-- capabilities
-- A capability is a named, versioned unit of functionality the Elastic Web
-- can expose (e.g. "bank.transfer", "browser.navigate").
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS capabilities (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,          -- e.g. 'bank.transfer'
    version         TEXT        NOT NULL DEFAULT '1.0.0',
    description     TEXT,
    category        TEXT,                                 -- e.g. 'banking', 'browser'
    status          TEXT        NOT NULL DEFAULT 'active',-- active | deprecated | disabled
    schema          JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- input/output contract
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- free-form evolving fields
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- intent_examples
-- Sample natural-language utterances mapped to a capability + extracted
-- parameters. Used to train/validate intent recognition.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS intent_examples (
    id              BIGSERIAL PRIMARY KEY,
    capability_id   BIGINT      REFERENCES capabilities(id) ON DELETE CASCADE,
    utterance       TEXT        NOT NULL,                 -- raw user text
    intent          TEXT        NOT NULL,                 -- normalized intent label
    parameters      JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- extracted slots
    language        TEXT        NOT NULL DEFAULT 'en',
    source          TEXT,                                 -- e.g. 'manual', 'synthetic', 'prod'
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- recipes
-- A recipe is a reusable, versioned plan (a graph of steps) that accomplishes
-- a goal. The current/latest version is referenced; full history lives in
-- recipe_versions.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recipes (
    id              BIGSERIAL PRIMARY KEY,
    name            TEXT        NOT NULL UNIQUE,
    slug            TEXT        NOT NULL UNIQUE,
    description     TEXT,
    current_version INTEGER     NOT NULL DEFAULT 1,
    status          TEXT        NOT NULL DEFAULT 'draft', -- draft | published | archived
    tags            JSONB       NOT NULL DEFAULT '[]'::jsonb,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- recipe_versions
-- Immutable snapshots of a recipe's definition at a given version number.
-- The 'definition' JSONB holds the full step graph / plan.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS recipe_versions (
    id              BIGSERIAL PRIMARY KEY,
    recipe_id       BIGINT      NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
    version         INTEGER     NOT NULL,
    definition      JSONB       NOT NULL DEFAULT '{}'::jsonb,  -- full step graph
    changelog       TEXT,
    created_by      TEXT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (recipe_id, version)
);

-- ---------------------------------------------------------------------------
-- execution_traces
-- One row per recipe execution run. High-level lifecycle + outcome.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execution_traces (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    recipe_id       BIGINT      REFERENCES recipes(id) ON DELETE SET NULL,
    recipe_version  INTEGER,
    status          TEXT        NOT NULL DEFAULT 'running', -- running | succeeded | failed | cancelled
    trigger         TEXT,                                   -- e.g. 'user', 'cron', 'api'
    input           JSONB       NOT NULL DEFAULT '{}'::jsonb,
    output          JSONB,
    error           JSONB,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    duration_ms     BIGINT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- execution_steps
-- Individual steps within an execution trace. Parent/child via parent_step_id
-- for nested step graphs.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS execution_steps (
    id              BIGSERIAL PRIMARY KEY,
    trace_id        BIGINT      NOT NULL REFERENCES execution_traces(id) ON DELETE CASCADE,
    step_key        TEXT        NOT NULL,                   -- logical step identifier
    parent_step_id  BIGINT      REFERENCES execution_steps(id) ON DELETE CASCADE,
    step_type       TEXT,                                   -- e.g. 'tool', 'llm', 'branch', 'subrecipe'
    status          TEXT        NOT NULL DEFAULT 'pending', -- pending | running | succeeded | failed | skipped
    input           JSONB,
    output          JSONB,
    error           JSONB,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    duration_ms     BIGINT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- evaluations
-- Results of evaluating a capability/recipe against a set of intent_examples
-- or a rubric. Scores are flexible JSONB.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evaluations (
    id              BIGSERIAL PRIMARY KEY,
    target_type     TEXT        NOT NULL,                   -- 'capability' | 'recipe' | 'intent'
    target_id       BIGINT      NOT NULL,
    evaluator       TEXT,                                    -- e.g. 'llm-judge', 'heuristic', 'human'
    score           JSONB       NOT NULL DEFAULT '{}'::jsonb, -- flexible score object
    passed          BOOLEAN,
    notes           TEXT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- benchmark_runs
-- A benchmark run executes a suite of cases and records aggregate results.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS benchmark_runs (
    id              BIGSERIAL PRIMARY KEY,
    run_id          UUID        NOT NULL DEFAULT gen_random_uuid() UNIQUE,
    name            TEXT        NOT NULL,
    suite           TEXT,                                    -- benchmark suite identifier
    status          TEXT        NOT NULL DEFAULT 'running',  -- running | completed | failed
    config          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    results         JSONB,                                   -- aggregate results
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at     TIMESTAMPTZ,
    duration_ms     BIGINT,
    metadata        JSONB       NOT NULL DEFAULT '{}'::jsonb
);

-- ---------------------------------------------------------------------------
-- Indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_capabilities_status        ON capabilities(status);
CREATE INDEX IF NOT EXISTS idx_capabilities_category      ON capabilities(category);
CREATE INDEX IF NOT EXISTS idx_capabilities_schema_gin    ON capabilities USING GIN (schema);
CREATE INDEX IF NOT EXISTS idx_capabilities_metadata_gin  ON capabilities USING GIN (metadata);

CREATE INDEX IF NOT EXISTS idx_intent_examples_capability ON intent_examples(capability_id);
CREATE INDEX IF NOT EXISTS idx_intent_examples_intent     ON intent_examples(intent);
CREATE INDEX IF NOT EXISTS idx_intent_examples_params_gin ON intent_examples USING GIN (parameters);

CREATE INDEX IF NOT EXISTS idx_recipes_status             ON recipes(status);
CREATE INDEX IF NOT EXISTS idx_recipes_tags_gin           ON recipes USING GIN (tags);

CREATE INDEX IF NOT EXISTS idx_recipe_versions_recipe     ON recipe_versions(recipe_id);

CREATE INDEX IF NOT EXISTS idx_execution_traces_recipe    ON execution_traces(recipe_id);
CREATE INDEX IF NOT EXISTS idx_execution_traces_status    ON execution_traces(status);
CREATE INDEX IF NOT EXISTS idx_execution_traces_started   ON execution_traces(started_at);
CREATE INDEX IF NOT EXISTS idx_execution_traces_input_gin  ON execution_traces USING GIN (input);

CREATE INDEX IF NOT EXISTS idx_execution_steps_trace      ON execution_steps(trace_id);
CREATE INDEX IF NOT EXISTS idx_execution_steps_parent     ON execution_steps(parent_step_id);
CREATE INDEX IF NOT EXISTS idx_execution_steps_status     ON execution_steps(status);

CREATE INDEX IF NOT EXISTS idx_evaluations_target         ON evaluations(target_type, target_id);

CREATE INDEX IF NOT EXISTS idx_benchmark_runs_name        ON benchmark_runs(name);
CREATE INDEX IF NOT EXISTS idx_benchmark_runs_status      ON benchmark_runs(status);
