# Elastic Web — Dependency Matrix

**Purpose:** Audit of upstream open-source infrastructure for the Elastic Web intent-driven semantic presentation layer. Goal: reuse mature infrastructure rather than rebuild it. The higher-level Elastic intelligence layer (Meta-Policy, recipe optimizer, learning) is **explicitly out of scope** and must NOT be implemented.

**Scope of the system this matrix serves:** intent IR, capability registry, capability retrieval (keyword + vector), progressive disclosure, MCP adapter, recipe storage/execution, telemetry, and benchmarking.

**Data collected:** 2026-09-10 via GitHub API + web search. Versions, licenses, and activity are real, current values — not estimates.

---

## Legend

| Recommendation | Meaning |
|---|---|
| **USE** | Adopt as a direct dependency / runtime component. |
| **REFERENCE** | Do not install; study the implementation and reimplement the minimal pattern. |
| **DEFER** | Valuable but not needed now; revisit at a later phase. |
| **ADAPT** | Take the concept/pattern, build a trimmed version for our needs. |

---

## 1. modelcontextprotocol/typescript-sdk

- **Repository:** https://github.com/modelcontextprotocol/typescript-sdk
- **Purpose:** Official TypeScript SDK for building MCP servers and clients.
- **License:** MIT → Apache-2.0 (transition in progress; new contributions Apache-2.0, older MIT).
- **Latest stable:** v2 SDK in development (pre-alpha on `main`); latest tagged release `@modelcontextprotocol/fastify@2.0.0` (2026-07-27). v1.x line stable.
- **Language:** TypeScript.
- **Key dependencies:** `@modelcontextprotocol/sdk` core, transport packages (stdio, SSE, streamable HTTP), zod for schemas.
- **Integration method:** npm package; used to build MCP servers/clients in a Node/TS stack.
- **Recommendation:** **USE** (only if the Elastic Web runtime is TypeScript/Node). If the runtime is Python, use the Python SDK instead — do not install both.
- **Overlaps:** Same protocol as python-sdk (1) and servers (3); the MCP adapter layer.
- **Security concerns:** MCP is a young protocol; validate tool schemas, restrict tool permissions, beware prompt-injection via tool descriptions. v2 is pre-alpha — pin to stable v1.x for production.
- **Maintenance/activity:** Very active (pushed 2026-09-10, 13.3k stars). Official Anthropic/ModelContextProtocol project.

## 2. modelcontextprotocol/python-sdk

- **Repository:** https://github.com/modelcontextprotocol/python-sdk
- **Purpose:** Official Python SDK for building MCP servers and clients.
- **License:** MIT.
- **Latest stable:** v2.2.0 (2026-09-07).
- **Language:** Python.
- **Key dependencies:** `anyio`, `httpx`, `pydantic`, `uvicorn` (server), `mcp` core.
- **Integration method:** pip package; build the MCP adapter server/client in Python.
- **Recommendation:** **USE** — this is the core MCP adapter dependency for a Python-based Elastic Web.
- **Overlaps:** Same protocol as typescript-sdk (1) and servers (3).
- **Security concerns:** Same MCP protocol concerns as (1). Pin to stable v2.x; v2 changed the API from v1.
- **Maintenance/activity:** Very active (pushed 2026-09-08, 24k stars). Official project.

## 3. modelcontextprotocol/servers

- **Repository:** https://github.com/modelcontextprotocol/servers
- **Purpose:** Reference implementations of MCP servers (filesystem, git, memory, fetch, etc.) plus a directory of community servers.
- **License:** MIT → Apache-2.0 transition (same as SDKs).
- **Latest stable:** No single version — a monorepo of reference servers; continuously updated (pushed 2026-09-03).
- **Language:** TypeScript (majority), some Python.
- **Key dependencies:** Varies per server; mostly the TypeScript SDK.
- **Integration method:** Reference source; run individual servers as subprocesses or adapt their patterns.
- **Recommendation:** **REFERENCE** — do not install the whole monorepo. Study the `memory`, `fetch`, and `filesystem` servers as patterns for our capability servers.
- **Overlaps:** Overlaps with both SDKs (1, 2); the `memory` server overlaps with mem0 (16).
- **Security concerns:** Reference servers are not hardened for untrusted input; never expose them directly to untrusted clients.
- **Maintenance/activity:** Very active (90k stars). Official project.

## 4. openai/openai-agents-python

- **Repository:** https://github.com/openai/openai-agents-python
- **Purpose:** OpenAI's lightweight multi-agent workflow framework (Agents SDK).
- **License:** MIT.
- **Latest stable:** v0.22.2 (2026-09-09).
- **Language:** Python.
- **Key dependencies:** `openai` client, `pydantic`, `httpx`.
- **Integration method:** pip package; agent/tool/guardrail abstractions.
- **Recommendation:** **DEFER** — not needed for capability retrieval/recipe execution. It is a competing agent-orchestration layer that overlaps with LangGraph (6) and the MCP adapter. Revisit only if we adopt OpenAI-native agent orchestration.
- **Overlaps:** LangGraph (6), MCP SDKs (1, 2), browser-use (13).
- **Security concerns:** Tied to OpenAI API; vendor lock-in. Guardrails are a useful pattern to reference.
- **Maintenance/activity:** Very active (29k stars, pushed 2026-09-09).

## 5. openai/openai-agents-js

- **Repository:** https://github.com/openai/openai-agents-js
- **Purpose:** OpenAI Agents SDK for JavaScript/TypeScript.
- **License:** MIT.
- **Latest stable:** v0.17.2 (2026-09-08).
- **Language:** TypeScript.
- **Key dependencies:** `openai` client, zod.
- **Integration method:** npm package.
- **Recommendation:** **DEFER** — same reasoning as (4); only relevant if the runtime is TS and we adopt OpenAI orchestration.
- **Overlaps:** LangGraph (6), MCP SDKs (1, 2).
- **Security concerns:** Vendor lock-in to OpenAI.
- **Maintenance/activity:** Active (3.8k stars, pushed 2026-09-10).

## 6. langchain-ai/langgraph

- **Repository:** https://github.com/langchain-ai/langgraph
- **Purpose:** Build resilient, stateful agent workflows as graphs (LangChain's orchestration layer).
- **License:** MIT.
- **Latest stable:** `langgraph==1.2.11` (langgraph-sdk 0.4.4, 2026-08-27).
- **Language:** Python (also JS).
- **Key dependencies:** `langchain-core`, `pydantic`, checkpoint backends (SQLite/Postgres).
- **Integration method:** pip package; graph/state-machine orchestration.
- **Recommendation:** **DEFER** — recipe execution here is a simple linear/conditional flow; a full graph framework is overkill. Reference its checkpointing pattern for durable recipe state.
- **Overlaps:** OpenAI Agents (4, 5), DSPy (17), LlamaIndex (18).
- **Security concerns:** Large dependency surface; pulls in langchain-core. Checkpoint stores need access control.
- **Maintenance/activity:** Very active (41k stars, pushed 2026-09-09).

## 7. microsoft/agent-framework

- **Repository:** https://github.com/microsoft/agent-framework
- **Purpose:** Microsoft's framework for building, orchestrating, and deploying AI agents and multi-agent workflows (Python + .NET).
- **License:** MIT.
- **Latest stable:** `python-1.17.0` (2026-09-03); dotnet line at 1.20.0.
- **Language:** Python, .NET.
- **Key dependencies:** `openai`/provider clients, `pydantic`, workflow/durable-task runtimes.
- **Integration method:** pip package; agent/workflow orchestration.
- **Recommendation:** **DEFER** — a competing multi-agent orchestration layer. Recipe execution here is a simple linear/conditional flow; a full agent framework is overkill. Reference its durable-workflow and human-in-the-loop patterns if we later need long-running recipe state.
- **Overlaps:** LangGraph (6), OpenAI Agents (4, 5), AutoGen (9), CrewAI (8).
- **Security concerns:** Large dependency surface; third-party model/provider usage is at your own risk per Microsoft's terms. Durable-task runtimes need access control.
- **Maintenance/activity:** Very active (13.3k stars, pushed 2026-09-03). Official Microsoft project.

## 8. crewAIInc/crewAI

- **Repository:** https://github.com/crewAIInc/crewAI
- **Purpose:** Framework for orchestrating role-playing, autonomous AI agents that collaborate on complex tasks.
- **License:** MIT.
- **Latest stable:** 1.15.18 (2026-08).
- **Language:** Python.
- **Key dependencies:** `openai`/provider clients, `pydantic`, `litellm`, `crewai-tools`.
- **Integration method:** pip package; role-based crew orchestration.
- **Recommendation:** **DEFER** — role-playing multi-agent orchestration is not needed for capability retrieval or recipe execution. Reference its tool/agent abstraction patterns only.
- **Overlaps:** LangGraph (6), OpenAI Agents (4, 5), AutoGen (9), Agent Framework (7).
- **Security concerns:** Heavy dependency tree (litellm, many tools); role-based autonomy can amplify prompt-injection risk.
- **Maintenance/activity:** Very active (58k stars, pushed 2026-08).

## 9. microsoft/autogen

- **Repository:** https://github.com/microsoft/autogen
- **Purpose:** Programming framework for agentic AI — multi-agent conversation and workflow orchestration.
- **License:** MIT (code, `LICENSE-CODE`); docs under CC-BY-4.0.
- **Latest stable:** `python-v0.7.5` (2025-09-30).
- **Language:** Python, .NET.
- **Key dependencies:** `openai`/provider clients, `pydantic`, `aiohttp`.
- **Integration method:** pip package; agent conversation/workflow orchestration.
- **Recommendation:** **DEFER** — same reasoning as Agent Framework (7) and CrewAI (8): a competing orchestration layer not needed for the minimal dependency set. Reference its agent-conversation and tool-use patterns.
- **Overlaps:** LangGraph (6), OpenAI Agents (4, 5), Agent Framework (7), CrewAI (8).
- **Security concerns:** Multi-agent conversation can be exploited via prompt injection between agents; large dependency surface.
- **Maintenance/activity:** Very active (60k stars). Official Microsoft project.

## 10. aurelio-labs/semantic-router

- **Repository:** https://github.com/aurelio-labs/semantic-router
- **Purpose:** Superfast semantic routing / intent classification using embeddings instead of LLM calls — maps an utterance to a route/function.
- **License:** MIT.
- **Latest stable:** v0.1.16 (PyPI); v0.2.0.dev1 is a dev pre-release (2026-08-24).
- **Language:** Python.
- **Key dependencies:** `numpy`, `nltk`, `scikit-learn`, optional `sentence-transformers` / `openai` embeddings.
- **Integration method:** pip package; define routes with example utterances, route incoming intents to capabilities.
- **Recommendation:** **USE** — this is the closest fit for **intent IR + capability retrieval (semantic)**. Lightweight, purpose-built, no LLM latency per call.
- **Overlaps:** Capability retrieval overlaps with pgvector (14) / qdrant (15) vector search; intent routing overlaps with DSPy (17).
- **Security concerns:** Embedding model choice affects routing accuracy; route definitions can be poisoned if user-controlled. Pin the embedding model.
- **Maintenance/activity:** Active (3.9k stars, pushed 2026-08-24). Use stable v0.1.16, not the dev release.

## 11. brandonburrus/dynamic-discovery-mcp

- **Repository:** https://github.com/brandonburrus/dynamic-discovery-mcp
- **Purpose:** Context management for MCP enabling dynamic tool discovery — agents see a short catalog of tools and load full definitions on demand.
- **License:** **None declared** (no LICENSE file).
- **Latest stable:** No tagged releases; single-maintainer project.
- **Language:** TypeScript.
- **Key dependencies:** MCP TypeScript SDK.
- **Integration method:** npm / source; MCP server that proxies tool discovery.
- **Recommendation:** **ADAPT** — the *concept* (progressive disclosure of tool/capability definitions) is exactly our **progressive disclosure** requirement, but the project is tiny (0 stars, no license, no releases). Reimplement the pattern ourselves rather than depend on it.
- **Overlaps:** Progressive disclosure overlaps with MCP SDKs (1, 2) and servers (3).
- **Security concerns:** **No license** — cannot legally depend on it. Single maintainer, no release process.
- **Maintenance/activity:** Low/early (0 stars, pushed 2026-08-12). Treat as a design reference only.

## 12. microsoft/playwright-mcp

- **Repository:** https://github.com/microsoft/playwright-mcp
- **Purpose:** MCP server that exposes browser automation (Playwright) as MCP tools.
- **License:** Apache-2.0.
- **Latest stable:** v0.0.80 (2026-09-01).
- **Language:** TypeScript.
- **Key dependencies:** `playwright`, `@modelcontextprotocol/sdk`.
- **Integration method:** npm package / standalone MCP server; run as a subprocess and connect via MCP.
- **Recommendation:** **USE** — the browser-automation capability server for the agentic web. Mature, Microsoft-maintained, exposes browser actions as MCP tools.
- **Overlaps:** Browser automation overlaps with browser-use (13).
- **Security concerns:** Browser automation is a high-risk capability — sandbox the browser, restrict navigation, validate URLs. Playwright is well-audited.
- **Maintenance/activity:** Very active (37k stars, pushed 2026-09-09).

## 13. browser-use/browser-use

- **Repository:** https://github.com/browser-use/browser-use
- **Purpose:** LLM-driven browser agent that autonomously completes tasks in a real browser.
- **License:** MIT.
- **Latest stable:** 0.13.10 (2026-09-04); core rebuilt in Rust (beta).
- **Language:** Python (core in Rust).
- **Key dependencies:** `playwright`, `langchain-core`, `pydantic`, LLM providers.
- **Integration method:** pip package; autonomous agent loop.
- **Recommendation:** **DEFER** — it is an *autonomous agent*, not a capability server. It overlaps with playwright-mcp (12) and the out-of-scope learning layer. Reference its browser-control patterns; use playwright-mcp for actual browser capability.
- **Overlaps:** playwright-mcp (12), OpenAI Agents (4), LangGraph (6).
- **Security concerns:** Autonomous browsing is high-risk (prompt injection from page content, credential exposure). Heavy dependency tree (langchain-core).
- **Maintenance/activity:** Very active (114k stars, pushed 2026-09-10).

## 14. pgvector/pgvector

- **Repository:** https://github.com/pgvector/pgvector
- **Purpose:** Open-source vector similarity search extension for PostgreSQL.
- **License:** PostgreSQL License (permissive, OSI-approved).
- **Latest stable:** v0.8.6 (tag).
- **Language:** C (PostgreSQL extension).
- **Key dependencies:** PostgreSQL (>= 13).
- **Integration method:** `CREATE EXTENSION vector`; SQL + client libs (psycopg, pgvector-python).
- **Recommendation:** **USE** — the vector store for **capability retrieval (vector)**. Reuses an existing Postgres instance, so capability registry + recipes + vectors live in one database. Smallest-footprint vector option.
- **Overlaps:** Vector search overlaps with qdrant (15).
- **Security concerns:** Requires Postgres hardening; HNSW index memory. No network-exposed service of its own.
- **Maintenance/activity:** Very active (23k stars, pushed 2026-09-08).

## 15. qdrant/qdrant

- **Repository:** https://github.com/qdrant/qdrant
- **Purpose:** High-performance vector database and vector search engine.
- **License:** Apache-2.0.
- **Latest stable:** v1.19.1 (2026-09-04).
- **Language:** Rust.
- **Key dependencies:** Standalone service; client SDKs (Python, JS).
- **Integration method:** Run as a service (Docker/binary); connect via REST/gRPC client.
- **Recommendation:** **DEFER** — choose **either** pgvector (14) **or** qdrant, not both. Qdrant is the better choice only if we need a dedicated, horizontally-scalable vector service without Postgres. For the smallest set, prefer pgvector.
- **Overlaps:** pgvector (14).
- **Security concerns:** Network-exposed service — needs auth/TLS. Rust core is memory-safe.
- **Maintenance/activity:** Very active (34k stars, pushed 2026-09-09).

## 16. mem0ai/mem0

- **Repository:** https://github.com/mem0ai/mem0
- **Purpose:** Memory layer for AI agents — persistent, self-updating memory across sessions.
- **License:** Apache-2.0.
- **Latest stable:** Mem0 Python SDK v2.0.20 (2026-08-20).
- **Language:** Python.
- **Key dependencies:** Vector store (qdrant/pgvector/etc.), LLM providers, `pydantic`.
- **Integration method:** pip package; memory add/search APIs.
- **Recommendation:** **DEFER** — memory/learning is part of the **out-of-scope** intelligence layer. Not needed for capability retrieval or recipe execution. Reference its memory-extraction pattern later.
- **Overlaps:** Vector stores (14, 15), MCP `memory` server (3).
- **Security concerns:** Memory extraction can leak sensitive data; needs PII controls. Depends on an external vector store.
- **Maintenance/activity:** Very active (65k stars, pushed 2026-09-09).

## 17. stanfordnlp/dspy

- **Repository:** https://github.com/stanfordnlp/dspy
- **Purpose:** Framework for programming (not prompting) LLMs — declarative modules, automatic prompt optimization, evaluation.
- **License:** MIT.
- **Latest stable:** 3.3.1 (2026-08-21).
- **Language:** Python.
- **Key dependencies:** `openai`/provider clients, `pydantic`, optional `litellm`.
- **Integration method:** pip package; `dspy.Predict`/`dspy.ChainOfThought` modules, optimizers, evaluators.
- **Recommendation:** **REFERENCE** — the **optimization/learning** part is out of scope. But its **evaluation/benchmarking** patterns (metrics, datasets, assertions) are directly useful for our **benchmarking** requirement. Study and reimplement the minimal eval harness; do not install the full framework.
- **Overlaps:** LangGraph (6), LlamaIndex (18), OpenAI Agents (4).
- **Security concerns:** Prompt-optimization can produce prompt-injection-prone prompts; eval harnesses must not execute untrusted code.
- **Maintenance/activity:** Very active (38k stars, pushed 2026-09-09).

## 18. run-llama/llama_index

- **Repository:** https://github.com/run-llama/llama_index
- **Purpose:** Leading data framework for RAG — document ingestion, indexing, retrieval, agents.
- **License:** MIT.
- **Latest stable:** v0.14.24 (2026-08-19).
- **Language:** Python.
- **Key dependencies:** `pydantic`, `numpy`, provider clients, optional vector stores.
- **Integration method:** pip package; `VectorStoreIndex`, retrievers, query engines.
- **Recommendation:** **DEFER** — a large, general RAG framework. Our capability retrieval is narrower (registry + keyword + vector over a small schema) and is better served by pgvector + semantic-router directly. Reference its retrieval abstractions.
- **Overlaps:** DSPy (17), LangGraph (6), vector stores (14, 15).
- **Security concerns:** Large dependency surface; many optional integrations. Version churn is high.
- **Maintenance/activity:** Very active (52k stars, pushed 2026-09-10).

## 19. open-telemetry/opentelemetry-collector

- **Repository:** https://github.com/open-telemetry/opentelemetry-collector
- **Purpose:** Vendor-agnostic telemetry collector — receives, processes, and exports traces/metrics/logs.
- **License:** Apache-2.0.
- **Latest stable:** v1.66.0 / v0.160.0 (2026-09-02).
- **Language:** Go.
- **Key dependencies:** Standalone service; OTLP protocol; exporter plugins.
- **Integration method:** Run as a service; instrument apps with OTel SDKs (Python/JS) that export OTLP to it.
- **Recommendation:** **DEFER** — the full collector is heavy for a single service. For the smallest set, use the **OTel SDKs** (Python/JS) and export directly to a backend. Add the collector only when we have multiple services or need buffering/processing.
- **Overlaps:** Telemetry overlaps with Phoenix (20) and Langfuse (21) as backends.
- **Security concerns:** Collector is a network service — needs auth/TLS. OTLP endpoints can be abused if exposed.
- **Maintenance/activity:** Very active (7.5k stars, pushed 2026-09-09). CNCF project.

## 20. Arize-ai/phoenix

- **Repository:** https://github.com/Arize-ai/phoenix
- **Purpose:** AI observability and evaluation platform — LLM tracing, evals, datasets.
- **License:** **Elastic License 2.0 (ELv2)** — NOT OSI open source; restricts use as a managed service and removes some rights.
- **Latest stable:** arize-phoenix v20.7.0 (2026-08-11).
- **Language:** Python.
- **Key dependencies:** `pandas`, `sqlalchemy`, `openinference`, vector store.
- **Integration method:** pip package; self-hosted web UI + SDK.
- **Recommendation:** **REFERENCE** — ELv2 license is a legal constraint for a product we may distribute. Study its eval/tracing patterns; prefer Langfuse (21) for an actual telemetry backend.
- **Overlaps:** Langfuse (21), OTel collector (19).
- **Security concerns:** ELv2 restricts managed-service use; self-hosted only. Heavy dependency tree.
- **Maintenance/activity:** Very active (11k stars, pushed 2026-09-10).

## 21. langfuse/langfuse

- **Repository:** https://github.com/langfuse/langfuse
- **Purpose:** Open-source AI engineering platform — LLM tracing, evals, metrics, prompt management, datasets. Integrates with OpenTelemetry.
- **License:** MIT Expat (core) + separate license for `ee/` directories (ClickHouse). Core is OSI open source.
- **Latest stable:** v4.33.0 (2026-09-09).
- **Language:** TypeScript (backend), React (web).
- **Key dependencies:** Postgres, ClickHouse (for analytics), Redis; OTel integration.
- **Integration method:** Self-hosted service (Docker) or Langfuse Cloud; SDKs (Python/JS) + OTel exporter.
- **Recommendation:** **USE** — the telemetry + benchmarking backend. MIT core, actively maintained, OTel-native, includes evals and datasets for our **benchmarking** requirement. Self-host via Docker.
- **Overlaps:** Phoenix (20), OTel collector (19).
- **Security concerns:** Self-hosted service needs auth; `ee/` code is not MIT — verify we only use core features. Postgres/ClickHouse/Redis footprint.
- **Maintenance/activity:** Very active (34k stars, pushed 2026-09-10).

---

## Recommended minimal dependency set

For an **intent-driven capability-retrieval + recipe-execution + benchmarking** system, the smallest set that covers all requirements:

| Requirement | Dependency | Recommendation |
|---|---|---|
| MCP adapter | `modelcontextprotocol/python-sdk` | **USE** |
| Intent IR + semantic capability retrieval | `semantic-router` | **USE** |
| Capability registry + recipes + vector retrieval (one DB) | `pgvector` (on Postgres) | **USE** |
| Browser capability server | `@playwright/mcp` | **USE** |
| Telemetry + benchmarking backend | `langfuse` (self-hosted) | **USE** |
| Telemetry instrumentation | OTel SDKs (Python/JS) — direct export | **USE** (SDKs only) |

**Total: 5 runtime dependencies + OTel SDKs.** Everything else is reference material.

**Rationale:**
- **One database** (Postgres + pgvector) holds the capability registry, recipe store, and vectors — no separate vector service.
- **semantic-router** gives intent→capability routing with embeddings, no per-call LLM latency.
- **python-sdk** is the single MCP adapter; **playwright-mcp** is the browser capability server.
- **langfuse** covers telemetry, evals, and benchmarking in one MIT-core self-hosted service; OTel SDKs feed it directly (no collector needed at this scale).
- Recipe execution is a simple linear/conditional flow — no graph framework required.

## DO NOT INSTALL

| Project | Why not |
|---|---|
| `openai-agents-python` / `openai-agents-js` | Vendor lock-in; competing orchestration layer; overlaps MCP + LangGraph. Not needed. |
| `langgraph` | Full graph framework is overkill for linear recipe execution; heavy langchain-core dependency. |
| `microsoft/agent-framework` | Competing multi-agent orchestration layer; overkill for linear recipe execution. |
| `crewAI` | Role-playing multi-agent orchestration; not needed for capability retrieval/recipe execution. |
| `microsoft/autogen` | Competing multi-agent orchestration layer; not needed for the minimal set. |
| `llama_index` | Large general RAG framework; our retrieval is narrower and served by pgvector + semantic-router. |
| `mem0` | Memory/learning is the out-of-scope intelligence layer. |
| `dspy` | Optimization/learning is out of scope; use only its eval patterns as reference. |
| `qdrant` | Redundant if pgvector is chosen — pick one vector store. |
| `opentelemetry-collector` | Heavy standalone service; use OTel SDKs with direct export at this scale. |
| `Arize-ai/phoenix` | **ELv2 license** (not OSI open source) — legal risk for distribution; Langfuse covers the need. |
| `browser-use` | Autonomous LLM agent, not a capability server; overlaps playwright-mcp; high-risk + heavy deps. |
| `dynamic-discovery-mcp` | **No license**, 0 stars, no releases — cannot legally depend on it; reimplement the progressive-disclosure pattern ourselves. |
| `modelcontextprotocol/servers` (as a dependency) | Reference monorepo, not a package; study individual servers only. |
| `modelcontextprotocol/typescript-sdk` | Only if the runtime is Python — use the Python SDK instead. |

---

*Generated 2026-09-10. Versions/licenses verified against GitHub API and upstream LICENSE files.*
