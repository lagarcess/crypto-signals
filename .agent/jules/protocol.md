# Jules Code Hygiene Protocol

> **Use this sequence before every commit.**
> If any step fails, stop and fix the error. Do not proceed to the next step.

### 1. Style & Syntax (The Pre-Flight)
*Standardize formatting and catch syntax errors immediately.*
```bash
poetry run ruff format .
poetry run ruff check . --fix
```

### 2. Type Safety (The Compiler)
*Catch logic bugs (e.g., passing strings to int functions) without running code.*
```bash
poetry run mypy src
```

### 3. Logic Verification (The Test Suite)
*Verify your implementation logic against the specs.*
```bash
poetry run pytest -q --tb=short
```

### 4. Runtime Smoke Test (The Integration)
*Does the app actually start? Connects to DB? Loads config?*
```bash
poetry run python -m crypto_signals.main --smoke-test
```
