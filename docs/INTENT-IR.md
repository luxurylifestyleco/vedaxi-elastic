# Intent IR (Intent Intermediate Representation)

The Intent IR is the structured, schema-validated description of a user's intent. It is the data contract produced by a compiler (rule-based or LLM) and consumed by downstream capability routing. It is the first stage of the Elastic pipeline and the foundation for minimizing intelligence cost: a well-structured intent lets retrieval and recipes do the work instead of a model.

## Files

| File | Purpose |
|---|---|
| `packages/intent-ir/intent_ir.py` | The `IntentIR` Pydantic v2 model. |
| `packages/intent-ir/schema.json` | The canonical JSON Schema (draft 2020-12) for the IR. |
| `packages/intent-ir/compiler.py` | The `IntentCompiler` interface and the rule-based implementation. |

## The `IntentIR` model

`IntentIR` is a Pydantic v2 `BaseModel` with `model_config = ConfigDict(extra="forbid")` — unknown fields are rejected, keeping the contract strict. All required string fields are validated to be non-blank.

### Fields

| Field | Type | Description |
|---|---|---|
| `intent_id` | `str` | Stable unique identifier for this intent instance. |
| `goal` | `str` | Canonical goal the user wants to achieve (e.g. `retrieve_financial_document`). |
| `domain` | `str` | Functional domain the intent belongs to (e.g. `banking`). |
| `action` | `str` | Verb describing the operation (e.g. `retrieve`). |
| `object` | `str` | The entity the action applies to (e.g. `account_statement`). |
| `constraints` | `Dict[str, Any]` | Structured constraints narrowing the intent (e.g. `period`). Default `{}`. |
| `context` | `Dict[str, Any]` | Ambient context informing execution (channel, session, source text). Default `{}`. |
| `desired_output` | `str` | Requested output format or artifact (e.g. `pdf`, `json`). |
| `authority` | `Dict[str, Any]` | Authorization/entitlement requirements. Default `{}`. |
| `disclosure` | `Dict[str, Any]` | Data-disclosure and privacy requirements. Default `{}`. |
| `success_conditions` | `List[str]` | Explicit conditions for the intent to be considered fulfilled. Default `[]`. |
| `confidence` | `float` | Compiler confidence in the parsed intent, 0.0–1.0. Default `1.0`. |
| `metadata` | `Dict[str, Any]` | Free-form metadata (compiler version, timestamps, provenance). Default `{}`. |

`IntentIR.new_id()` generates a fresh `intent_id` (UUID4 hex).

### How intents are structured

An intent is decomposed into the routing-relevant dimensions that downstream layers use:

- **goal** — the canonical outcome, used as the primary routing key (e.g. `retrieve_financial_document`).
- **domain** — the functional area (e.g. `banking`).
- **action** — the verb (e.g. `retrieve`, `create`, `update`, `delete`).
- **object** — the entity the action applies to (e.g. `account_statement`, `invoice`).
- **desired_output** — the requested artifact (e.g. `pdf`).
- **context** — ambient information that informs execution but does not narrow the intent.
- **constraints** — structured narrowing (e.g. `{"period": "2026-08"}`).

Retrieval concatenates `goal`, `domain`, `action`, `object`, and `desired_output` into a searchable blob (`_intent_text` in `retriever.py`), so these five fields are the routing surface.

## The JSON schema

`schema.json` is the language-neutral, canonical definition of the IR. It is a draft 2020-12 schema with `additionalProperties: false` and all 13 fields required. It mirrors the Pydantic model field-for-field, including the `confidence` bounds (0.0–1.0) and the `success_conditions` array of strings. This is the contract a non-Python consumer (or a future LLM compiler emitting JSON) must satisfy.

## The compiler

`compiler.py` defines the stable compilation interface and a deterministic rule-based implementation.

### Interface

```python
class IntentCompiler(ABC):
    @abstractmethod
    def compile(self, text: str) -> IntentIR:
        """Compile a natural-language request into an IntentIR.

        Raises:
            ValueError: if the text cannot be parsed into an intent.
        """
```

The interface is deliberately decoupled from the implementation so a real LLM compiler can be swapped in later without changing downstream consumers.

### `RuleBasedCompiler`

The current implementation is a simple, deterministic rule-based parser — a structural placeholder, not a sophisticated intent engine. It:

1. Rejects empty text.
2. Matches the lowercased input against a table of document rules (regex → object, domain, action, goal, desired_output):

   | Pattern | object | domain | action | goal | desired_output |
   |---|---|---|---|---|---|
   | `bank statement` | `account_statement` | `banking` | `retrieve` | `retrieve_financial_document` | `pdf` |
   | `(credit card )?statement` | `account_statement` | `banking` | `retrieve` | `retrieve_financial_document` | `pdf` |
   | `invoice` | `invoice` | `billing` | `retrieve` | `retrieve_financial_document` | `pdf` |
   | `receipt` | `receipt` | `billing` | `retrieve` | `retrieve_financial_document` | `pdf` |

3. Extracts a `period` constraint (`YYYY-MM`) if a month name is mentioned, using the current year as the default.
4. Builds an `IntentIR` with `context={"source_text": text}`, `success_conditions=[f"{object} delivered as {output}"]`, `confidence=0.9`, and `metadata={"compiler": "rule-based", "version": "0.1.0"}`.
5. Raises `ValueError` if no rule matches.

A module-level `default_compiler = RuleBasedCompiler()` instance is provided for convenience.

## Example

Compiling `"Get my August bank statement"` produces an `IntentIR` roughly like:

```python
IntentIR(
    intent_id="<uuid4-hex>",
    goal="retrieve_financial_document",
    domain="banking",
    action="retrieve",
    object="account_statement",
    constraints={"period": "2026-08"},
    context={"source_text": "Get my August bank statement"},
    desired_output="pdf",
    authority={},
    disclosure={},
    success_conditions=["account_statement delivered as pdf"],
    confidence=0.9,
    metadata={"compiler": "rule-based", "version": "0.1.0"},
)
```

## Tests

`packages/intent-ir` contains 15 tests covering the model validators, the schema, and the compiler.
