# Third-Party Notices

This project reuses and references the following open-source projects. See
`docs/DEPENDENCY-MATRIX.md` for the full audit (purpose, license, version,
integration method, and recommendation for each).

## Direct dependencies

| Project | License | Usage | Source |
|---|---|---|---|
| Pydantic | MIT | Data models (IntentIR, Capability, Recipe, events) | https://github.com/pydantic/pydantic |
| pytest | MIT | Test suite | https://github.com/pytest-dev/pytest |
| jsonschema | MIT | Intent IR JSON Schema validation | https://github.com/python-jsonschema/jsonschema |

## Referenced / studied (not runtime dependencies)

| Project | License | Why referenced |
|---|---|---|
| modelcontextprotocol/python-sdk | MIT | MCP adapter reference (thin swap target) |
| modelcontextprotocol/typescript-sdk | MIT | MCP protocol reference |
| modelcontextprotocol/servers | MIT | Reference server implementations |
| openai/openai-agents-python | MIT | Agent runtime reference |
| openai/openai-agents-js | MIT | Agent runtime reference |
| langchain-ai/langgraph | MIT | Workflow graph reference |
| microsoft/agent-framework | MIT | Multi-agent orchestration reference |
| crewAIInc/crewAI | MIT | Role-based multi-agent orchestration reference |
| microsoft/autogen | MIT (code) | Multi-agent conversation framework reference |
| aurelio-labs/semantic-router | MIT | Semantic routing reference |
| brandonburrus/dynamic-discovery-mcp | MIT | Progressive disclosure reference |
| microsoft/playwright-mcp | MIT | Browser fallback reference |
| browser-use/browser-use | Apache-2.0 | Browser automation reference |
| pgvector/pgvector | PostgreSQL | Vector storage (not installed; JSONB fallback) |
| qdrant/qdrant | Apache-2.0 | Vector DB reference |
| mem0ai/mem0 | Apache-2.0 | Memory reference |
| stanfordnlp/dspy | MIT | Optimization reference |
| run-llama/llama_index | MIT | Research/data reference |
| open-telemetry/opentelemetry-collector | Apache-2.0 | Telemetry reference |
| Arize-ai/phoenix | Elastic-2.0 | Telemetry/eval reference |
| langfuse/langfuse | MIT | Telemetry/eval reference |

## Notes

- No third-party source code is vendored into this repository.
- No API keys or secrets are committed.
- All demo-bank data is synthetic; no real financial credentials are used.
