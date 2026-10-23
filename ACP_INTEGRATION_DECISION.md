---
domain: VEDAXI_ELASTIC
---

# ACP integration decision

**Decision: reject. Do not add an ACP adapter.**

ACP here is the [Agent Client Protocol](https://hermes-agent.nousresearch.com/docs/user-guide/features/acp) as implemented by Hermes (`hermes acp`). It is not A2A, and it is not an "Agent Comm Protocol."

No adapter, dependency, or test host was added. Hermes' programmatic integration guide says the three transports below all drive the same `AIAgent`. They differ by wire format and by which host features they expose. None of them gives Elastic Web a capability the book can select that A2A, MCP, or HTTP request-response does not already cover.

Hermes' own choice guide sends non-IDE programs to the API server, not to ACP. That API is still a chat frontend in front of one Hermes agent. It is not a reason to add a fourth protocol client.

## What Hermes says ACP is

Sources, read 2026-10-17:

- [ACP Host Integration](https://hermes-agent.nousresearch.com/docs/user-guide/features/acp)
- [Programmatic Integration](https://hermes-agent.nousresearch.com/docs/developer-guide/programmatic-integration)
- [API Server](https://hermes-agent.nousresearch.com/docs/user-guide/features/api-server)
- [TUI](https://hermes-agent.nousresearch.com/docs/user-guide/tui)

`hermes acp` is a stdio JSON-RPC server. The host is an editor (VS Code, Zed, JetBrains) or a bridge that pretends to be one (Buzz). The agent keeps Hermes' provider credentials, memory, skills, and tools. The host owns the conversation.

The ACP surface Hermes documents is session lifecycle, not a capability catalog:

- `session/new`, prompt submission, cancel, fork, resume
- streamed message chunks and thinking
- tool-call events rendered as editor diffs and terminal blocks
- permission prompts: `allow_once`, `allow_session`, `allow_always`, `deny`
- editor-supplied MCP servers attached to that session

Stdout is reserved for JSON-RPC. Logs go to stderr. The `hermes-acp` toolset includes `terminal` and `execute_code`. A host may answer permission requests itself. Buzz does that with `allow_once`, so shell commands run with no human prompt. Hermes says `approvals.mode: manual` does not stop that. `allow_always` writes Hermes' permanent allowlist.

## What Elastic Web already does

Checked in this repo on 2026-10-17:

| Need | Existing contract |
| --- | --- |
| Turn a business intent into a goal | `RuleBasedCompiler` → `IntentIR` |
| Choose work from the capability book | `KeywordRetriever` plus recipe composition |
| Call a tool on another process | `RemoteMCPAdapter`: stdio JSON-RPC, or one HTTP POST and one JSON body. SSE is not implemented |
| Delegate a task and poll it | `A2AAdapter.discover_http`: agent card, `SendMessage`, `GetTask`. `SendStreamingMessage` is not called. `CancelTask` is not called |
| Call a website tool | Declarative WebMCP form (`toolname` / `tooldescription`). The custom `/capabilities/{id}/execute` client is not the WebMCP spec |
| Stop a sensitive side effect | `AuthorizationGuard.check` at the start of `_unified_executor`, before any adapter runs |
| Record the run | `RecipeStore.execute` emits one result per step, then telemetry events |

Recipes return one result per step (`packages/recipe-schema/store.py`). Streamed tokens, editor diffs, and slash-command sessions are not part of that contract. Elastic Web does not already have a stream consumer. That missing consumer is not a reason to adopt an editor protocol.

## Three Hermes transports

| | ACP over stdio | OpenAI-compatible HTTP + SSE | TUI gateway JSON-RPC |
| --- | --- | --- | --- |
| Who it is for | IDEs that already speak ACP | Chat frontends (Open WebUI, LobeChat, curl) | A custom UI that wants Hermes sessions, slash commands, approvals, and streaming |
| Transport | JSON-RPC on stdio. `hermes acp` | `hermes gateway` on `127.0.0.1:8642`. `stream: true` is SSE. Bearer `API_SERVER_KEY` | JSON-RPC on stdio, or WebSocket via `tui_gateway/ws.py`. The API server does not serve this channel. `HERMES_TUI_GATEWAY_URL` is the dashboard's loopback, not a public attach port |
| Discovery | No agent card and no tool list for the capability book. Tools are frozen inside a Hermes session after eager MCP discovery | `GET /v1/models` is one model name. `GET /v1/capabilities` is feature flags. `GET /v1/skills` and `GET /v1/toolsets` list Hermes skill and tool names (`read_file`, `write_file`, …). Those names are not input schemas the book can bind | `gateway.capabilities`, `commands.catalog`. Still a Hermes session, not a book entry |
| Execution | Prompt in, editor events out | One chat completion or `POST /v1/runs`. The final text is the result. Tool progress is UX chrome | `prompt.submit` plus a large session/control catalog |
| Streaming | Required for the editor experience | Optional. Non-streaming JSON works. Runs also have `GET /v1/runs/{id}/events` | `message.delta` and tool events |
| Cancel | Session cancel | `POST /v1/runs/{id}/stop`. Chat reports `finish_reason: cancelled` | `session.interrupt` |
| Approval | Host must answer ACP permission requests. A host can auto-allow. Timeout denies. `allow_always` persists on the Hermes host | `POST /v1/runs/{id}/approval` can send `once` and resume Hermes' own tool. That is not `AuthorizationGuard` | Server-to-client `approval` request. A WebSocket client that never sends `client.capabilities` has the request withdrawn |
| Auth | Provider secrets in `~/.hermes/.env`, inherited by the subprocess. Terminal `--setup` can open provider login | `API_SERVER_KEY` plus the same provider secrets on the host | Same Hermes profile |
| Remote | Local subprocess only | HTTP on the gateway host. This is the remote option Hermes documents | Stdio is local. WebSocket attach is an embedded gateway, not a general remote port |
| Normalization | Diffs, tool cards, thinking chunks | Assistant text, plus `hermes.tool.progress` when streaming | Dozens of event and request types |
| Cost | Install Hermes, the `acp` extra, provider credentials, and optionally Chromium. Elastic Web becomes an editor host of a shell-capable agent | Install and run `hermes gateway`. Elastic Web becomes a chat client of that same agent | Same install, plus a second JSON-RPC session protocol |

## Requirement check

| Requirement | ACP | HTTP + SSE | TUI gateway | Already in Elastic Web |
| --- | --- | --- | --- | --- |
| Capability discovery into the book | No stable tool catalog | Hermes skill and tool names, not `Capability` schemas | Hermes command catalog | MCP `tools/list`, A2A agent card, declarative form |
| Task execution | Prompt session | Chat completion or run | `prompt.submit` | MCP `tools/call`, A2A `SendMessage` |
| Streaming | Yes | Yes, if the client asks | Yes | Not consumed. Steps return one result |
| Cancellation | Yes | Yes | Yes | Not required. A2A's spec has `CancelTask`; this adapter does not call it |
| Approval | Editor prompt the host may skip | Run approval the HTTP client may answer | Host must answer `approval` | `AuthorizationGuard` before the call |
| Authentication | Hermes provider secrets on the subprocess | Bearer key plus those secrets | Same | Principal, permissions, explicit approval |
| Remote deployment | No | Yes | Not as a public attach port | A2A JSON-RPC HTTP and MCP HTTP request-response |
| Result normalization | Editor blocks | Assistant text | Event soup | `ExecutionResult` and one recipe result per step |
| Operational complexity | Highest for an IDE protocol we do not host | Medium, and it is a chatbot API | Highest protocol surface | Keep the current adapters |

## Why an adapter is not justified

Elastic Web's job is to select a capability from the book and run it. ACP does not publish those capabilities. It publishes an editor session whose tools are Hermes' file, terminal, and code-execution set. Putting that session behind one book entry named "Hermes" would hide the tools the book is supposed to select, and it would run them with Hermes' credentials.

`GET /v1/toolsets` does not close that gap. It lists names inside one Hermes agent. Calling one still means sending a prompt and letting Hermes choose the tool, including `terminal`. MCP already lists real tools with schemas and invokes one tool per call.

The permission model conflicts with the guard we have. ACP's useful editor behavior is a live approval dialog. Headless hosts auto-answer it. Elastic Web would be that headless host. `allow_always` writes a second authorization store outside `AuthorizationGuard`. The runs API has the same shape: the client posts `choice: once` and Hermes continues.

Streaming is the feature ACP, SSE, and the TUI gateway add. The recipe runtime does not consume a stream. Building one only so Hermes can show token deltas does not change a business outcome.

If the need is "ask another agent to do a bounded task and return a result," A2A already does that. If the need is "call a declared tool," MCP already does that. If the need is "POST JSON and read JSON," the HTTP adapters already do that.

## What would change this decision

Reconsider only if one of these becomes true:

1. Elastic Web must attach to an agent that speaks Agent Client Protocol and nothing else: no A2A agent card, no MCP `tools/list`, no HTTP tool endpoint. The smallest path is still Hermes' documented one: spawn `hermes acp`, keep stdout clean, and surface permission requests to a person. Do not auto-allow `terminal` or `execute_code`.
2. ACP grows a method that returns stable tool schemas (name, description, JSON inputs) that register as `Capability` records and run as one call under `AuthorizationGuard`, with the shell toolset absent. The docs read on 2026-10-17 do not have that method.
3. A recipe consumer requires token deltas or editor diffs as the business result, and the only producer is an ACP-only agent. `RecipeStore.execute` currently returns one value per step.

`GET /v1/skills` and `GET /v1/toolsets` do not meet (2). They describe Hermes. They do not replace the book.

Until one of those is true, do not implement ACP, the TUI gateway client, or an SSE chat client.

## Evidence

- Hermes ACP guide, programmatic integration (three protocols, same `AIAgent`), API server (`/v1/skills`, `/v1/toolsets`, `/v1/runs/{id}/approval`, `/v1/runs/{id}/stop`), and TUI (API server does not expose the TUI JSON-RPC channel).
- Repo check on 2026-10-17: no ACP client or server. A2A discovery is `discover_http` (`SendMessage` / `GetTask` only). Remote MCP is stdio or one JSON POST. `_unified_executor` checks `AuthorizationGuard` before dispatch. `RecipeStore.execute` stores one result per step.
- No Hermes process was started. A live `hermes acp` session needs a local install, provider credentials, and a toolset that can run a shell. That run is not required to reject the adapter, and it is not a safe acceptance test.

## Code

None. Adding a protocol client here would only increase the protocol count.
