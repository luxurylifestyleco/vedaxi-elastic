# Elastic Web — Runnable Examples

End-to-end runnable demonstration scripts illustrating the complete lifecycle of intents, capability discovery, multi-step recipe execution, and gateway API communication.

## Scripts

### 1. Intent Compilation (`01_compile_intent.py`)
Demonstrates compiling natural language inputs into strongly typed `IntentIR` objects with constraints and desired output formats.
```bash
.venv/Scripts/python.exe examples/01_compile_intent.py
```

### 2. Capability Discovery & Retrieval (`02_retrieve_capabilities.py`)
Loads all 64 capabilities from the demo-bank manifest, builds a keyword retriever, and scores candidate capabilities for given intent goals.
```bash
.venv/Scripts/python.exe examples/02_retrieve_capabilities.py
```

### 3. Multi-Step Recipe Execution (`03_execute_recipe.py`)
Initializes the pre-registered `RecipeStore` (Control C), executes multi-step DAGs against demo-bank functions, and reports execution latencies and step outputs.
```bash
.venv/Scripts/python.exe examples/03_execute_recipe.py
```

### 4. Full Gateway API Roundtrip (`04_full_gateway_roundtrip.py`)
Spins up the HTTP gateway on an ephemeral port in-process and tests the REST endpoints for `/health`, `/intent/compile`, `/capabilities/discover`, capability execution, and recipe resolution.
```bash
.venv/Scripts/python.exe examples/04_full_gateway_roundtrip.py
```
