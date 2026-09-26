# Intent IR V1

Conversational Intent Intermediate Representation.

V1 records **what the user wants**. It does not plan, route, compile, retrieve, or execute.

The existing Elastic `schema.json` / `IntentIR` model is a **compiled execution contract**: every field is required and blank strings are rejected. That contract cannot represent "Call Mom.", "Send this to Mom.", "Nothing overnight.", or a later "Actually, make that Friday." without inventing values. V1 is the missing language. It sits **beside** the compiled contract. It does not replace it.

Canonical files:

| File | Role |
|------|------|
| `intent_ir.schema.json` | Draft 2020-12 JSON Schema |
| `intent_ir_examples.json` | 29-utterance validation corpus |
| `test_intent_ir_v1.py` | Schema validation tests |

Insertion:

- Elastic (public): `packages/intent-ir/` — same package as the compiled contract.
- Elastic (private Mastermind): `packages/intent-ir/` — byte-identical V1 files.
- VDX: `VDX/intent-ir/` — shared language for Sonic, not a Kotlin parser.

A later compiler may project a *resolved* V1 document onto the compiled `IntentIR`. That projection is not V1.

---

## Success criterion

> A simple intent stays simple, a complex intent can become richer, preferences and exclusions retain their meaning, unresolved information stays unresolved, and later conversation can update the same intent without changing the schema.

---

## Design properties

- **Versioned** — `schema_version` is the constant `"1.0"`.
- **Serializable** — one JSON object. No code objects, no live pointers.
- **Deterministic** — the same document always validates the same way. Validation does not parse language.
- **Extensible** — new meaning is a new `slots[].name` or a new `preferences`/`exclusions` `path`. Top-level fields do not grow in V1.
- **Easy to validate** — JSON Schema draft 2020-12, `additionalProperties: false`.
- **Human-readable** — field names are English; `surface` keeps the original words.

V1 does **not** contain: capabilities, recipes, plans, authority, disclosure, success conditions, desired output, confidence, compiler metadata, or an LLM.

---

## Document shape

Only three fields are required:

```json
{
  "schema_version": "1.0",
  "intent_id": "hmm",
  "revision": 1
}
```

That is a valid intent. Everything else is optional so an incomplete utterance does not force invented structure.

---

## Fields

### `schema_version`

Constant `"1.0"`. Identifies the language, not the intent.

```json
"schema_version": "1.0"
```

### `intent_id`

Stable identity of **this** intent. Later turns reuse it. They do not mint a new id and they do not change the schema.

```json
"intent_id": "flight-london"
```

### `revision`

Monotonic snapshot number for that `intent_id`, starting at 1. Each conversational update writes a new revision of the same intent.

```json
"revision": 4
```

"Find a flight to London." is revision 1. "Nothing overnight." is revision 2 of the same id. "I'd prefer Emirates." is revision 3. "Actually, make that Friday." is revision 4. Schema unchanged.

### `source_text`

The latest utterance that produced this revision. Optional. Never a substitute for structured fields.

```json
"source_text": "Actually, make that Friday."
```

### `action`

The verb, as a **slot**. Absent when the utterance does not name one. Unresolved when the verb is known to be missing. Never a required blank string.

```json
"action": { "status": "resolved", "value": "call", "surface": "Call" }
```

Bare "Cancel." is just an action. Bare "Hmm." has no action.

### `object`

The primary entity the action applies to. May stay unresolved (`"this"`, `"that one"`, `"her"`).

```json
"object": { "status": "unresolved", "value": null, "surface": "this" }
```

### `target`

App, channel, or provider. Distinct from object: "Open WhatsApp" has a target and no object; "Call Mom" has an object and no target; "Call Mom on WhatsApp" has both.

```json
"target": { "status": "resolved", "value": "WhatsApp", "surface": "WhatsApp" }
```

### `domain`

Optional coarse domain. Never required. Leave absent rather than guessing `communication` for "Call Mom."

### `slots`

Named extra fields. This is the V1 extension point.

Each item is a slot with a required `name`. Common names in the corpus: `query`, `recipient`, `content`, `ordinal`, `destination`, `when`, `occasion`, `state`. New meaning is a new name, not a new top-level field.

```json
"slots": [
  { "name": "destination", "status": "resolved", "value": "London", "surface": "London" },
  { "name": "when", "status": "resolved", "value": "Friday", "surface": "Friday" }
]
```

### `preferences`

Soft wants. They must not be collapsed into resolved slots.

"I'd prefer Emirates." does **not** set `slots[{name: airline, value: Emirates}]`. It appends a preference. The airline remains unchosen.

```json
"preferences": [
  { "path": "airline", "value": "Emirates", "surface": "I'd prefer Emirates" }
]
```

### `exclusions`

Hard nos. They must not be dropped, and they must not be rewritten as positive slots.

"Nothing overnight." does **not** become `when: daytime`. It is an exclusion on `schedule`.

```json
"exclusions": [
  { "path": "schedule", "value": "overnight", "surface": "Nothing overnight" }
]
```

---

## Slot

Used by `action`, `object`, `target`, `domain`, and every `slots[]` item.

| Field | Required | Meaning |
|-------|----------|---------|
| `status` | yes | `resolved` \| `unresolved` \| `ambiguous` |
| `name` | on `slots[]` only | The extra field's name |
| `value` | when `status` is `resolved` | The known content. Null when unresolved. Never invented. |
| `surface` | no | Original words |
| `candidates` | no | Competing values when `ambiguous` |

Status meanings:

- **resolved** — a value is known. `value` is required and must not be null.
- **unresolved** — a gap is known. `value` is null or omitted. The schema still represents the intent.
- **ambiguous** — competing candidates, no winner. `value` is omitted. `candidates` lists the options.

```json
"object": {
  "status": "ambiguous",
  "surface": "John",
  "candidates": ["John Home", "John Work"]
}
```

`action` / `object` / `target` / `domain` omit `name` because the field name is implicit.

---

## Constraint

Used by `preferences[]` and `exclusions[]`.

| Field | Required | Meaning |
|-------|----------|---------|
| `path` | yes | Dimension (`airline`, `tone`, `schedule`, `diet`, `cuisine`, `price`, `target`, …). Not a JSON Pointer. |
| `value` | yes | The preferred or excluded value |
| `surface` | no | Original words |

A preference does not resolve a slot. An exclusion does not delete a slot. Both survive later revisions unless a later utterance explicitly replaces them.

---

## Worked examples

### Simple stays simple — "Call Mom."

```json
{
  "schema_version": "1.0",
  "intent_id": "call-mom",
  "revision": 1,
  "source_text": "Call Mom.",
  "action": { "status": "resolved", "value": "call", "surface": "Call" },
  "object": { "status": "resolved", "value": "Mom", "surface": "Mom" }
}
```

No domain, no target, no slots, no constraints.

### Deixis stays unresolved — "Send this to Mom."

```json
{
  "schema_version": "1.0",
  "intent_id": "send-mom",
  "revision": 1,
  "source_text": "Send this to Mom.",
  "action": { "status": "resolved", "value": "send", "surface": "Send" },
  "object": { "status": "unresolved", "value": null, "surface": "this" },
  "slots": [
    { "name": "recipient", "status": "resolved", "value": "Mom", "surface": "Mom" }
  ]
}
```

### Preference retains meaning — "Something sarcastic." (same intent)

```json
{
  "schema_version": "1.0",
  "intent_id": "send-mom",
  "revision": 2,
  "source_text": "Something sarcastic.",
  "action": { "status": "resolved", "value": "send", "surface": "Send" },
  "object": { "status": "unresolved", "value": null, "surface": "this" },
  "slots": [
    { "name": "recipient", "status": "resolved", "value": "Mom", "surface": "Mom" }
  ],
  "preferences": [
    { "path": "tone", "value": "sarcastic", "surface": "Something sarcastic" }
  ]
}
```

`this` is still unresolved. Sarcasm is a preference, not invented message text.

### Exclusion retains meaning, then a later turn updates the same intent

1. "Find a flight to London." → `intent_id: flight-london`, revision 1, destination London.
2. "Nothing overnight." → revision 2, same id, exclusion `schedule=overnight`.
3. "I'd prefer Emirates." → revision 3, preference `airline=Emirates`. Destination and the overnight exclusion survive.
4. "Actually, make that Friday." → revision 4, slot `when=Friday`. Schema still V1. Preference and exclusion still present.

### Incomplete is valid — "Hmm."

```json
{
  "schema_version": "1.0",
  "intent_id": "hmm",
  "revision": 1,
  "source_text": "Hmm."
}
```

### Ambiguous is not resolved — "Call John."

```json
{
  "schema_version": "1.0",
  "intent_id": "call-john",
  "revision": 1,
  "source_text": "Call John.",
  "action": { "status": "resolved", "value": "call", "surface": "Call" },
  "object": {
    "status": "ambiguous",
    "surface": "John",
    "candidates": ["John Home", "John Work"]
  }
}
```

---

## What V1 refuses

- Filling `object.value` for "this" / "that one" / "her".
- Turning "I'd prefer Emirates" into a resolved airline slot.
- Turning "Nothing overnight" into a positive schedule.
- Requiring `domain`, `desired_output`, `authority`, or `success_conditions` on a spoken command.
- Adding top-level fields for each new utterance type.
- Testing an LLM. The corpus tests the schema, not a parser.

---

## Relation to the compiled Elastic IntentIR

| | V1 (`intent_ir.schema.json`) | Compiled (`schema.json`) |
|--|------------------------------|--------------------------|
| Job | Represent user intent, including gaps | Feed capability routing |
| Required | `schema_version`, `intent_id`, `revision` | 13 fields, none blank |
| Unresolved | first-class `status` | cannot be expressed |
| Preferences / exclusions | first-class arrays | would be flattened into `constraints` |
| Multi-turn | same `intent_id`, new `revision` | new `intent_id` per compile |
| Used by | VDX Sonic + Elastic conversational layer | Elastic retrieval / recipes |

Do not merge the two. A projection from a *fully resolved* V1 document onto compiled `IntentIR` is a later compiler concern.

---

## Validation

```bash
# Elastic public
python -m pytest packages/intent-ir/test_intent_ir_v1.py -q

# VDX copy
python -m pytest VDX/intent-ir/test_intent_ir_v1.py -q
```

The tests load `intent_ir.schema.json`, check the schema itself, validate every corpus example, and reject documents that invent extra fields, drop required identity, resolve without a value, or omit `name` on `slots[]`.
