# Engineering Knowledge Base
*Central repository of lessons learned, API quirks, and architectural gotchas.*

## General
- [2024-03-20] **Workflow**: Always run `/verify` before PR to catch regression.
- [2026-01-20] **Architecture**: Engines (`ExecutionEngine`) create domain objects but Repositories (`PositionRepository`) must persist them. Ensure orchestration layer bridges this gap.
- [2026-01-20] **Testing**: When mocking execution logic, ensure `ENVIRONMENT` settings match expected behavior (e.g., `PROD` + `ENABLE_EXECUTION=False` -> triggers Theoretical fallback).
- [2026-01-20] **Testing**: `MagicMock(spec=PydanticModel)` does not automatically populate model fields as attributes. You must explicitly set them (e.g., `mock_pos.side = ...`) or use a helper, otherwise `AttributeError` occurs on access.
- [2026-01-20] **Testing**: When introducing new dependencies (e.g., `RiskEngine` inside `ExecutionEngine`), ensure existing unit tests patch the new dependency to avoid side effects (e.g., network calls or unexpected rejections) in legacy tests.
- [2026-01-20] **CI/CD**: Do NOT add `conftest.py` to mock GCP credentials if GitHub Secrets already has `GOOGLE_APPLICATION_CREDENTIALS` and deploy.yml passes it to the environment. Trust existing infrastructure instead of adding redundant mocking layers that violate project conventions.
- [2026-01-20] **Code Organization**: Artifacts folder is for permanent project documentation; temporary documentation (summaries, PR drafts, debug files) belongs in `temp/` folder. This keeps the repo clean and separates working files from deliverables.
- [2026-01-20] **Testing Conventions**: `conftest.py` is a pytest plugin file for global fixtures, not a test module. Follow naming convention: test files are `test_*.py` or `*_test.py`. Adding conftest for one-off credential mocks violates this and confuses IDEs/linters.

## APIs & Integrations
### Alpaca
- [2024-XX-XX] **Orders**: Market orders during extended hours are rejected. Use Limit orders.
- [2026-01-20] **Typing**: Alpaca SDK v2 objects often need explicit casting (e.g., `cast(Order, response)`) to satisfy Mypy strict checks, especially when accessing `status` or `id` on union types.

### Firestore
- [2024-XX-XX] **Queries**: Composite queries require an index. Check logs for the creation link.
- [2026-01-20] **Aggregation**: `count()` queries with filters (e.g., `.where("status", "==", "OPEN")`) REQUIRE a Composite Index (e.g., `status` ASC + `asset_class` ASC). Missing index causes GRPC errors.

### GCP
- [2024-XX-XX] **Cloud Run**: Cold starts can exceed 10s. JIT warmup is essential.
- [2026-01-21] **BigQuery**: `insert_rows_json` does NOT support automatic schema evolution. Columns must exist in the table definition.
- [2026-01-21] **Staging Tables**: When altering a Fact table, the Staging table MUST be dropped and recreated (`CREATE TABLE ... LIKE ...`) to match the new schema.
- [2026-01-21] **Secrets**: Never commit SQL scripts with hardcoded Project IDs. Use placeholders and injection.

### Alpaca
- [2026-01-21] **Typing**: Account fields (e.g., `buying_power`) can be returned as strings, decimals, or floats depending on the API version and field. Always use defensive parsing (`float(val)` with try-except) when mapping to strict schemas.

### Pydantic & Data Pipelines
- [2026-01-21] **Constraint Paradox**: Strict Pydantic validators (e.g., `PositiveFloat`) are excellent for data integrity but can catch "conceptually valid" failures (like a negative stop loss due to weird volatility) and crash the pipeline.
- [2026-01-21] **Safe Hydration Pattern**: To persist these "invalid" objects for analysis without relaxing the schema, use a "Safe Hydration" strategy:
  1. Catch the validation error early.
  2. Populate the strict fields with a safe constant (e.g., `0.0001` for `PositiveFloat` or explicit `SAFE_CONSTANTS`).
  3. Store the *real* invalid values in a metadata field (e.g., `rejection_reason` string or `trace` dict).
  4. Flag the object status clearly (e.g., `REJECTED_BY_FILTER`).
- [2026-01-21] **Zombie Prevention**: When routing these hydrate objects to analytics pipelines, explicitly bypass simulation logic (like market data fetching) that assumes valid data, or implementation will fail downstream. Force `PnL = 0` to preserve statistical integrity.
