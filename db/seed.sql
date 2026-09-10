-- ============================================================================
-- Elastic Web — seed.sql
-- Sample rows for every table. Idempotent: truncates the 8 tables first, then
-- inserts fresh sample data, so re-running is always clean.
-- ============================================================================

-- Reset tables (CASCADE handles FK dependencies). Order-independent.
TRUNCATE TABLE
    capabilities,
    intent_examples,
    recipes,
    recipe_versions,
    execution_traces,
    execution_steps,
    evaluations,
    benchmark_runs
RESTART IDENTITY CASCADE;

-- capabilities ---------------------------------------------------------------
INSERT INTO capabilities (name, version, description, category, status, schema, metadata) VALUES
  ('bank.transfer', '1.0.0', 'Transfer money between accounts', 'banking', 'active',
   '{"input":{"type":"object","properties":{"from":{"type":"string"},"to":{"type":"string"},"amount":{"type":"number"}}},"output":{"type":"object","properties":{"confirmation_id":{"type":"string"}}}}',
   '{"owner":"payments-team","sla_ms":2000}'),
  ('browser.navigate', '1.0.0', 'Navigate a browser to a URL', 'browser', 'active',
   '{"input":{"type":"object","properties":{"url":{"type":"string"}}},"output":{"type":"object","properties":{"title":{"type":"string"}}}}',
   '{"owner":"browser-team","headless":true}'),
  ('bank.balance', '1.1.0', 'Read account balance', 'banking', 'active',
   '{"input":{"type":"object","properties":{"account":{"type":"string"}}},"output":{"type":"object","properties":{"balance":{"type":"number"}}}}',
   '{"owner":"payments-team","read_only":true}')
ON CONFLICT (name) DO NOTHING;

-- intent_examples ------------------------------------------------------------
INSERT INTO intent_examples (capability_id, utterance, intent, parameters, language, source, metadata) VALUES
  ((SELECT id FROM capabilities WHERE name='bank.transfer'), 'send 50 dollars to my savings', 'transfer',
   '{"amount":50,"currency":"USD","to":"savings"}', 'en', 'manual', '{"confidence":0.98}'),
  ((SELECT id FROM capabilities WHERE name='bank.transfer'), 'move money from checking to savings', 'transfer',
   '{"from":"checking","to":"savings"}', 'en', 'prod', '{"confidence":0.91}'),
  ((SELECT id FROM capabilities WHERE name='browser.navigate'), 'open the elastic web docs', 'navigate',
   '{"url":"https://docs.elasticweb.dev"}', 'en', 'manual', '{"confidence":0.95}'),
  ((SELECT id FROM capabilities WHERE name='bank.balance'), 'what is my balance', 'balance',
   '{}', 'en', 'manual', '{"confidence":0.99}');

-- recipes --------------------------------------------------------------------
INSERT INTO recipes (name, slug, description, current_version, status, tags, metadata) VALUES
  ('monthly-budget-review', 'monthly-budget-review', 'Summarize spending and flag budget overruns', 1, 'published',
   '["finance","reporting"]', '{"owner":"finance-team"}'),
  ('web-research-digest', 'web-research-digest', 'Gather and summarize web research on a topic', 1, 'published',
   '["research","browser"]', '{"owner":"research-team"}')
ON CONFLICT (name) DO NOTHING;

-- recipe_versions ------------------------------------------------------------
INSERT INTO recipe_versions (recipe_id, version, definition, changelog, created_by, metadata) VALUES
  ((SELECT id FROM recipes WHERE name='monthly-budget-review'), 1,
   '{"steps":[{"key":"fetch-transactions","type":"tool","capability":"bank.transactions"},{"key":"summarize","type":"llm","prompt":"Summarize spending"}]}',
   'Initial version', 'seed', '{"reviewed":true}'),
  ((SELECT id FROM recipes WHERE name='web-research-digest'), 1,
   '{"steps":[{"key":"search","type":"tool","capability":"browser.navigate"},{"key":"extract","type":"tool"},{"key":"digest","type":"llm"}]}',
   'Initial version', 'seed', '{"reviewed":true}');

-- execution_traces -----------------------------------------------------------
INSERT INTO execution_traces (trace_id, recipe_id, recipe_version, status, trigger, input, output, started_at, finished_at, duration_ms, metadata) VALUES
  (gen_random_uuid(), (SELECT id FROM recipes WHERE name='monthly-budget-review'), 1, 'succeeded', 'user',
   '{"month":"2026-08"}', '{"summary":"Spending within budget","overruns":[]}',
   now() - interval '2 hours', now() - interval '2 hours' + interval '3 seconds', 3000, '{"env":"dev"}'),
  (gen_random_uuid(), (SELECT id FROM recipes WHERE name='web-research-digest'), 1, 'failed', 'cron',
   '{"topic":"pgvector"}', NULL,
   now() - interval '1 hour', now() - interval '1 hour' + interval '45 seconds', 45000, '{"env":"dev"}');

-- execution_steps -------------------------------------------------------------
INSERT INTO execution_steps (trace_id, step_key, parent_step_id, step_type, status, input, output, error, started_at, finished_at, duration_ms, metadata) VALUES
  ((SELECT id FROM execution_traces WHERE trigger='user' LIMIT 1), 'fetch-transactions', NULL, 'tool', 'succeeded',
   '{"account":"checking"}', '{"count":120}', NULL,
   now() - interval '2 hours', now() - interval '2 hours' + interval '1 second', 1000, '{}'),
  ((SELECT id FROM execution_traces WHERE trigger='user' LIMIT 1), 'summarize', NULL, 'llm', 'succeeded',
   '{"transactions":120}', '{"summary":"Spending within budget"}', NULL,
   now() - interval '2 hours' + interval '1 second', now() - interval '2 hours' + interval '3 seconds', 2000, '{"model":"gpt-4o"}'),
  ((SELECT id FROM execution_traces WHERE trigger='cron' LIMIT 1), 'search', NULL, 'tool', 'failed',
   '{"query":"pgvector"}', NULL, '{"code":"TIMEOUT","message":"search tool timed out"}',
   now() - interval '1 hour', now() - interval '1 hour' + interval '45 seconds', 45000, '{}');

-- evaluations -----------------------------------------------------------------
INSERT INTO evaluations (target_type, target_id, evaluator, score, passed, notes, metadata) VALUES
  ('capability', (SELECT id FROM capabilities WHERE name='bank.transfer'), 'llm-judge',
   '{"accuracy":0.95,"fluency":0.9,"overall":0.93}', true, 'Handles standard transfers well', '{"model":"gpt-4o"}'),
  ('intent', (SELECT id FROM intent_examples WHERE utterance='send 50 dollars to my savings'), 'heuristic',
   '{"slot_f1":0.88}', true, 'Slots extracted correctly', '{}'),
  ('recipe', (SELECT id FROM recipes WHERE name='monthly-budget-review'), 'human',
   '{"usefulness":4,"clarity":5}', true, 'Good output, minor formatting', '{"reviewer":"alice"}');

-- benchmark_runs --------------------------------------------------------------
INSERT INTO benchmark_runs (run_id, name, suite, status, config, results, started_at, finished_at, duration_ms, metadata) VALUES
  (gen_random_uuid(), 'intent-recognition-v1', 'intent', 'completed',
   '{"cases":120,"model":"gpt-4o"}',
   '{"accuracy":0.93,"latency_p50_ms":210,"latency_p95_ms":480}',
   now() - interval '1 day', now() - interval '1 day' + interval '4 minutes', 240000, '{"runner":"elastic-bench"}'),
  (gen_random_uuid(), 'recipe-execution-smoke', 'recipe', 'completed',
   '{"recipes":["monthly-budget-review","web-research-digest"]}',
   '{"pass_rate":0.5,"total":2,"passed":1,"failed":1}',
   now() - interval '30 minutes', now() - interval '30 minutes' + interval '2 minutes', 120000, '{"runner":"elastic-bench"}');
