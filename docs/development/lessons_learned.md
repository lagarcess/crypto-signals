# Lessons Learned: BigQuery Migration & Runtime Fixes
Date: 2026-02-17

## 1. Schema Validation Traps
**Context**: `SchemaGuardian` raised "Critical Error: Missing columns" for fields like `scaled_out_prices`.
**Lesson**: Pydantic fields marked with `exclude=True` (often used for runtime-only state) must be explicitly skipped validation logic that compares Models to Database Schemas.
**Action**: Updated `SchemaGuardian._validate_fields` to check `field_info.exclude`.

## 2. Metric Observability Gaps
**Context**: "Signals Found" was 0 while "Signal Generation" metric count was 10 (should be 19).
**Lesson**: Conditional metric recording (only inside `else` or `if` blocks) leads to undercounting. Top-level metrics (e.g., "signals processed") must be recorded outside conditional logic paths.
**Action**: Moved `metrics.record_success` to the main loop scope in `main.py`.

## 3. Dynamic BigQuery Configuration
**Context**: Hardcoded dataset names prevented safe testing in DEV.
**Lesson**: Use `ClassVar` on Pydantic models to map to BigQuery tables dynamically, and use a "Fuzzy Lookup" strategy (checking `_test` suffix) to handle environment divergence seamlessly.
**Action**: Implemented `_bq_table_name` and `migrate_bq_descriptions.py`.
