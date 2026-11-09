# Intent revision and interruption safeguards

Local implementation, 2026-11-09. No deployment or live-provider validation.

## Existing boundaries retained

IntentIR now carries a strict positive integer `intent_revision` (default `1`).
It is correlation data, not a permission grant. Existing RecipeDAGRunner,
verification, A2A stores and chat session authorization remain the authorities.

Revision-aware A2A clients send both `metadata.intentId` and
`metadata.intentRevision`, with a valid chat `sessionId` and owned `contextId`.
New requests for the same scoped intent must increase the revision and use a
new `messageId`. Retry the same message ID only for the same revision/context.
Legacy messages without explicit revision binding retain their behavior.

The local memory and SQLite task stores reject superseded or duplicate
revisions before dispatch and discard late results. Revision identity includes
owner, session and context. SQLite serializes admission/finalization within an
immediate transaction, including across store instances, and persists the
revision through restart. Task identity cannot be rewritten during updates.

Tasks are now stored before dispatch, so cancellation is observable while a
provider is running. A canceled or paused task cannot later become completed.
Active cancellation discards results but does not promise provider effects were
undone. Connection failures report an unknown execution outcome requiring
reconciliation. Permission/approval failures remain nonterminal `auth-required`.
A new revision/message still requires current authorization before execution.

Chat authorization is rechecked before dispatch, after execution and after
verification. REST `/message:send` uses the same session authorization for
chat/revision requests as JSON-RPC. End-of-response and stream exhaustion no
longer imply terminal success; verification-pending and approval-paused tasks
remain nonterminal, including idempotent replay.

## Memory boundary

Actual semantic and procedural memory belongs to the existing private
`Vedaxi-Elastic-Web-Mastermind` implementation, not this public capability
retriever. Its companion change provides isolated advisory recall, binds grant
digests to revision/authority/disclosure, and checks snapshots around existing
plan-cache lookup. Recalled facts cannot restore permission or replace current
intent fields. Semantic recall has no production serving-path caller today;
this work verifies the interface and existing procedural-cache boundary, not a
deployed semantic planner.

## Verification and limits

Focused tests exercise older-revision results, duplicate revisions, concurrent
SQLite stores, restart, immutable context, cancellation before/during execution,
paused-task cancellation, provider timeout/disconnect, client callback
disconnect, approval pause, session revocation, REST auth, and replay validation.
A synthetic positive verifier ensures interruption tests would otherwise claim
completion. No external providers are invoked.

PostgreSQL revision persistence is not implemented by the current chat schema.
Explicit revision-bound requests fail closed on that backend before dispatch.
No migration was authored or applied. PostgreSQL multi-process cancellation and
live database/RLS behavior are unverified. The process-local backend is not
restart-safe. Client socket delivery failure is not proof of provider rollback;
the tests cover local callback interruption and provider connection failures,
not a live end-to-end network loss after fulfillment.
