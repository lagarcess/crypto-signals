# Engineering Knowledge Base
*Central repository of lessons learned, API quirks, and architectural gotchas.*

## General
- [2024-03-20] **Workflow**: Always run `/verify` before PR to catch regression.
- [2026-01-22] **Workflow**: Implement a "Branch Guard" in verification scripts to prevent accidental commits to `main`. This is safer than relying solely on server-side protection during local development.
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
- [2026-01-22] **SDK Limitations**: The `TradingClient` (v2) in `alpaca-py` lacks a `get_account_activities` method. Use the raw REST method `client.get("/account/activities", params=...)` instead.
- [2026-01-22] **Raw API**: When using `client.get`, `date` objects in parameters must be explicitly converted to string (ISO format). Response objects are raw dicts/lists and should be wrapped (e.g., `_ActivityWrapper`) to maintain object attribute compatibility with typed codebases.
- [2026-01-22] **CFEE Settlement**: Crypto fees are posted as asynchronous `CFEE` events at T+1 (end of day), not at transaction time. Real-time logging requires an 'Estimated Fee' model, followed by a T+1 'Patch Pipeline' to reconcile actuals.

### Pydantic & Data Pipelines
- [2026-01-21] **Constraint Paradox**: Strict Pydantic validators (e.g., `PositiveFloat`) are excellent for data integrity but can catch "conceptually valid" failures (like a negative stop loss due to weird volatility) and crash the pipeline.
- [2026-01-21] **Safe Hydration Pattern**: To persist these "invalid" objects for analysis without relaxing the schema, use a "Safe Hydration" strategy:
  1. Catch the validation error early.
  2. Populate the strict fields with a safe constant (e.g., `0.0001` for `PositiveFloat` or explicit `SAFE_CONSTANTS`).
  3. Store the *real* invalid values in a metadata field (e.g., `rejection_reason` string or `trace` dict).
  4. Flag the object status clearly (e.g., `REJECTED_BY_FILTER`).
- [2026-01-21] **Zombie Prevention**: When routing these hydrate objects to analytics pipelines, explicitly bypass simulation logic (like market data fetching) that assumes valid data, or implementation will fail downstream. Force `PnL = 0` to preserve statistical integrity.
- [2026-01-21] **Dependency Injection**: Initialize GCP-related clients (Firestore, BigQuery) in engine constructors via optional arguments. This allows unit tests to inject `MagicMock` and prevents `DefaultCredentialsError` in CI environments that lack project-level authentication.
- [2026-01-21] **Pipeline Robustness**: Always guard date-based dataframe filtering (`df[df.index >= dt]`) with an `.empty` check. Pandas comparisons against empty indexes can raise `TypeError` or `ValueError` in certain contexts, crashing the pipeline for illiquid assets.

### Firestore
- [2026-01-21] **Cooldown Logic**: Queries for most recent status exits (e.g., TP1_HIT) with a limit of 1 MUST have a composite index on `symbol` (ASC), `status` (ASC), and `timestamp` (DESC) to allow 48-hour time window filtering.

## Implementation & Scripting
- [2026-01-22] **Scripting**: Distinguish between standalone **setup/verification scripts** (`scripts/` root) and **operational module scripts** (`src/crypto_signals/scripts/`). Module scripts enable `python -m` execution and cleaner project imports.
- [2026-01-22] **Bootstrapping**: If a module requires environment variables (e.g., `ENVIRONMENT=PROD`) to be set *before* importing project configuration (which reads env on load), use `os.environ.setdefault()` followed by `# noqa: E402` on imports. This suppresses linter errors for non-top-level imports where order of execution is critical for proper initialization.
- [2026-01-22] **BigQuery**: When bridging from a schema-less (Firestore) to rigid (BigQuery) system, any field added to the source must be manually propagated through the ETL pipeline models (Pydantic) and added to BQ via `ALTER TABLE`. Pydantic handles NoSQL defaults (None), but BigQuery execution will fail on "unknown field" if the SQL schema is not evolved first.
- [2026-01-22] **Diagnostic Output**: Always direct transient diagnostic outputs to a gitignored `temp/reports/` folder. Standardize workflow temporary files in `temp/` subfolders (issues/, plan/, pr/, etc.) to maintain workspace hygiene.

## Testing & CI/CD
- [2026-01-23] **Dependency Injection**: Use explicit dependency injection (e.g., `repository=MagicMock()`) in engine constructors rather than relying on `conftest.py` patches or redundant mocks. This ensures unit tests never attempt to initialize real Cloud clients (Firestore/BigQuery) which causes `DefaultCredentialsError` in CI.
- [2026-01-23] **Schema Parity**: For integration tests involving BigQuery, create test tables using `CREATE TABLE ... LIKE PROD_TABLE`. Manually maintaining `_test` table definitions leads to drift and "Column not found" errors when production schemas evolve.
- [2026-01-23] **Property Mocking**: When testing logic that relies on `self.property` calling an external service (e.g., `ExecutionEngine.account`), mock the *class property* (`ExecutionEngine.account`) or the underlying client method, depending on architectural depth. Mocking the property directly is cleaner for unit tests.
- [2026-01-24] **Micro-Cap Safeguards**: Mathematical formulas (like `low - 0.5 * ATR`) break for assets with prices < 0.00001. Always implement a mathematical floor (Layer 1) AND an execution quantity cap (Layer 2) to prevent negative values and position sizing explosions.
- [2026-01-25] **CI Credential Safety**: `SignalGenerator` (and other engines) default to real Cloud Clients (e.g., `SignalRepository`) if no dependency is injected. This causes `DefaultCredentialsError` in CI. **Always** inject `MagicMock` for repositories in unit tests to prevent accidental cloud connection attempts.
