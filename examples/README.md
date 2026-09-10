# Examples

This directory holds runnable examples for the Elastic Web public SDK.

> **Status:** The examples directory is scaffolded but currently empty. The
> packages are flat source modules wired together at test time via each
> package's `conftest.py` (sys.path insertion), so there is not yet a
> pip-installable distribution to import from in a standalone example script.
> Once the packages are packaged (see `docs/PUBLICATION-READINESS.md`), add
> runnable examples here, e.g.:
>
> - `intent_ir.py` — build and validate an IntentIR document.
> - `capability_retrieval.py` — retrieve top-K capabilities for an intent.
> - `recipe_execution.py` — execute a pre-authored recipe with zero model calls.
> - `benchmark.py` — run the Control A/B/C benchmark comparison.
