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
- [2026-01-25] **Simulation Safety**: Running production pipelines locally (e.g., `main.py` with `ENVIRONMENT=PROD`) carries side effects if state reconciliation is active. If the local environment (e.g., Paper) differs from the DB target (Prod), reconcilers may incorrectly flag live data as "Zombies" and destructively update the DB. Always use read-only diagnostic scripts for production checks.

## APIs & Integrations
### Alpaca
- [2024-XX-XX] **Orders**: Market orders during extended hours are rejected. Use Limit orders.
- [2026-01-20] **Typing**: Alpaca SDK v2 objects often need explicit casting (e.g., `cast(Order, response)`) to satisfy Mypy strict checks, especially when accessing `status` or `id` on union types.
- [2026-01-21] **Typing**: Account fields (e.g., `buying_power`) can be returned as strings, decimals, or floats depending on the API version and field. Always use defensive parsing (`float(val)` with try-except) when mapping to strict schemas.
- [2026-01-22] **SDK Limitations**: The `TradingClient` (v2) in `alpaca-py` lacks a `get_account_activities` method. Use the raw REST method `client.get("/account/activities", params=...)` instead.
- [2026-01-22] **Raw API**: When using `client.get`, `date` objects in parameters must be explicitly converted to string (ISO format). Response objects are raw dicts/lists and should be wrapped (e.g., `_ActivityWrapper`) to maintain object attribute compatibility with typed codebases.
- [2026-01-22] **CFEE Settlement**: Crypto fees are posted as asynchronous `CFEE` events at T+1 (end of day), not at transaction time. Real-time logging requires an 'Estimated Fee' model, followed by a T+1 'Patch Pipeline' to reconcile actuals.
- [2026-01-25] **404 Handling**: A `404 Not Found` from Alpaca's `get_open_position` does NOT imply the position was closed manually. It handles both "never existed" and "already closed". To confirm a manual exit, you must explicitly search `get_orders(status='filled', side=OPPOSITE)` for a closing trade. Relying on 404 alone leads to false positives ("Exit Gaps").
- [2026-01-27] **Typing**: When using `alpaca-py` request objects in conditional blocks (Crypto vs Equity), assign them to distinct variables (e.g., `crypto_req` vs `stock_req`) rather than reusing a generic `req` variable. This avoids Mypy union type confusion where it cannot infer the specific attributes available on `req` later in the block.
- [2026-01-27] **Typing**: Always use `alpaca.trading.enums` (e.g., `QueryOrderStatus.CLOSED`) instead of raw strings for API requests. Mypy strict mode often flags raw strings as incompatible with the expected Enum type.

### Firestore
- [2024-XX-XX] **Queries**: Composite queries require an index. Check logs for the creation link.
- [2026-01-20] **Aggregation**: `count()` queries with filters (e.g., `.where("status", "==", "OPEN")`) REQUIRE a Composite Index (e.g., `status` ASC + `asset_class` ASC). Missing index causes GRPC errors.
- [2026-01-21] **Cooldown Logic**: Queries for most recent status exits (e.g., TP1_HIT) with a limit of 1 MUST have a composite index on `symbol` (ASC), `status` (ASC), and `timestamp` (DESC) to allow 48-hour time window filtering.

### GCP
- [2024-XX-XX] **Cloud Run**: Cold starts can exceed 10s. JIT warmup is essential.
- [2026-01-21] **BigQuery**: `insert_rows_json` does NOT support automatic schema evolution. Columns must exist in the table definition.
- [2026-01-21] **Staging Tables**: When altering a Fact table, the Staging table MUST be dropped and recreated (`CREATE TABLE ... LIKE ...`) to match the new schema.
- [2026-01-21] **Secrets**: Never commit SQL scripts with hardcoded Project IDs. Use placeholders and injection.
- [2026-01-21] **Dependency Injection**: Initialize GCP-related clients (Firestore, BigQuery) in engine constructors via optional arguments. This allows unit tests to inject `MagicMock` and prevents `DefaultCredentialsError` in CI environments that lack project-level authentication.

### Pydantic & Data Pipelines
- [2026-01-21] **Constraint Paradox**: Strict Pydantic validators (e.g., `PositiveFloat`) are excellent for data integrity but can catch "conceptually valid" failures (like a negative stop loss due to weird volatility) and crash the pipeline.
- [2026-01-21] **Safe Hydration Pattern**: To persist these "invalid" objects for analysis without relaxing the schema, use a "Safe Hydration" strategy:
  1. Catch the validation error early.
  2. Populate the strict fields with a safe constant (e.g., `0.0001` for `PositiveFloat` or explicit `SAFE_CONSTANTS`).
  3. Store the *real* invalid values in a metadata field (e.g., `rejection_reason` string or `trace` dict).
  4. Flag the object status clearly (e.g., `REJECTED_BY_FILTER`).
- [2026-01-21] **Zombie Prevention**: When routing these hydrate objects to analytics pipelines, explicitly bypass simulation logic (like market data fetching) that assumes valid data, or implementation will fail downstream. Force `PnL = 0` to preserve statistical integrity.
- [2026-01-21] **Pipeline Robustness**: Always guard date-based dataframe filtering (`df[df.index >= dt]`) with an `.empty` check. Pandas comparisons against empty indexes can raise `TypeError` or `ValueError` in certain contexts, crashing the pipeline for illiquid assets.
- [2026-01-26] **Reserved Keywords**: Pydantic models with fields named `class` (a Python keyword) cannot be instantiated via constructor kwargs (e.g., `Asset(class="crypto")` raises SyntaxError). specific `model_validate` or `Field(alias="class")` is required, but `model_validate({"class": "..."})` is the safest runtime approach for external data.


## Implementation & Scripting
- [2026-01-22] **Scripting**: Distinguish between standalone **setup/verification scripts** (`scripts/` root) and **operational module scripts** (`src/crypto_signals/scripts/`). Module scripts enable `python -m` execution and cleaner project imports.
- [2026-01-22] **Bootstrapping**: If a module requires environment variables (e.g., `ENVIRONMENT=PROD`) to be set *before* importing project configuration (which reads env on load), use `os.environ.setdefault()` followed by `# noqa: E402` on imports. This suppresses linter errors for non-top-level imports where order of execution is critical for proper initialization.
- [2026-01-22] **BigQuery**: When bridging from a schema-less (Firestore) to rigid (BigQuery) system, any field added to the source must be manually propagated through the ETL pipeline models (Pydantic) and added to BQ via `ALTER TABLE`. Pydantic handles NoSQL defaults (None), but BigQuery execution will fail on "unknown field" if the SQL schema is not evolved first.
- [2026-01-22] **Diagnostic Output**: Always direct transient diagnostic outputs to a gitignored `temp/reports/` folder. Standardize workflow temporary files in `temp/` subfolders (issues/, plan/, pr/, etc.) to maintain workspace hygiene.
- [2026-01-27] **Firestore ETL**: When moving data from Firestore (NoSQL) to BigQuery (SQL), the Firestore document ID (`doc.id`) is NOT part of the document data payload (`doc.to_dict()`). You must explicitly map it (e.g., `data['doc_id'] = doc.id`) during the extract phase if you need to reference it later (e.g., for cleanup/deletion). Failure to do so results in implicit ID loss and failed deletion logic.
- [2026-01-27] **Shell Security**: Scripts accepting user input (like PR numbers) must validate input rigorously (e.g., `[[ "$1" =~ ^[0-9]+$ ]]`). Unvalidated inputs in `gh api` calls can lead to SSRF or path traversal if the input is used to construct file paths.
- [2026-01-27] **Poetry Installation**: Prefer the official installer (`install.python-poetry.org`) over `pip install poetry`. The official installer isolates Poetry's dependencies from the system/project environment, preventing version conflicts with libraries like `requests` or `urllib3`.

## Testing & CI/CD
- [2026-01-27] **Testing**: `contextlib.ExitStack` is required when patching more than ~20 objects in a single test. Python's `with (...)` statement has a limit on statically nested blocks, which causes `SyntaxError: too many statically nested blocks`. Use `stack.enter_context(patch(...))` to bypass this limit dynamically.
- [2026-01-27] **Config Validation**: Strict Pydantic validators (e.g., "Field cannot be empty") in `config.py` act globally. If a unit test wants to test "disabled execution" mode by setting a key to empty, the global validator will crash the test setup. Use `@model_validator` with conditional logic (e.g., `if self.ENABLE_EXECUTION: check_keys()`) instead of unconditional field validators.
- [2026-01-23] **Dependency Injection**: Use explicit dependency injection (e.g., `repository=MagicMock()`) in engine constructors rather than relying on `conftest.py` patches or redundant mocks. This ensures unit tests never attempt to initialize real Cloud clients (Firestore, BigQuery) which causes `DefaultCredentialsError` in CI.
- [2026-01-23] **Schema Parity**: For integration tests involving BigQuery, create test tables using `CREATE TABLE ... LIKE PROD_TABLE`. Manually maintaining `_test` table definitions leads to drift and "Column not found" errors when production schemas evolve.
- [2026-01-23] **Property Mocking**: When testing logic that relies on `self.property` calling an external service (e.g., `ExecutionEngine.account`), mock the *class property* (`ExecutionEngine.account`) or the underlying client method, depending on architectural depth. Mocking the property directly is cleaner for unit tests.
- [2026-01-24] **Micro-Cap Safeguards**: Mathematical formulas (like `low - 0.5 * ATR`) break for assets with prices < 0.00001. Always implement a mathematical floor (Layer 1) AND an execution quantity cap (Layer 2) to prevent negative values and position sizing explosions.
- [2026-01-25] **CI Credential Safety**: `SignalGenerator` (and other engines) default to real Cloud Clients (e.g., `SignalRepository`) if no dependency is injected. This causes `DefaultCredentialsError` in CI. **Always** inject `MagicMock` for repositories in unit tests to prevent accidental cloud connection attempts.
- [2026-01-26] **Refactoring & Coverage**: When extracting logic from a "God Class" (e.g., `SignalGenerator`) to a helper class (e.g., `SignalParameterFactory`), you **MUST** create a dedicated test suite for the new helper. relying on the original class's tests will likely result in a massive coverage drop (e.g., from 80% to 20%) because the new file is technically "untested" even if it's used.
- [2026-01-26] **Mocking Risks**: `MagicMock` objects cast to `float()` default to `1.0`. If a mock method name is typoed (e.g. `mock.get_val` instead of `mock.get_value`), the mock object itself is returned, coercing to `1.0` and causing silent numeric failures in tests.
- [2026-01-26] **MyPy Legacy Strategy**: For large codebases with deep legacy type errors, do not use `type: ignore` everywhere. Use `pyproject.toml` `[[tool.mypy.overrides]]` with `ignore_errors = true` for specific modules. This unblocks CI immediately while strictly enforcing types on new code.
- [2026-01-26] **Pytest Debugging**: If `pytest` collects 0 tests or fails silently, check for `NameError` at the module level (e.g., missing `import pytest` when using `@pytest.mark.skip`). These import errors in test files can abort collection without a clear traceback unless `--collect-only` is used.
- [2026-01-26] **SDK Stability**: The `alpaca-py` SDK v2 may deprecate or internalize methods (like `_get` becoming `_request` or changing behaviors). When fixing "AttributeError: object has no attribute 'x'", verify the available methods using `dir(obj)` or source inspection to distinguish between a renamed internal method and a logic error.
- [2026-01-26] **Internal APIs**: Relying on internal methods (starting with `_`) is fragile. If a public alternative exists (like `get_account_activities`), prefer it. However, if the public method returns strictly typed objects that break legacy dictionary-based logic, it may be safer to use the lower-level `_request` with explicit type verification (`isinstance(x, dict)`) as a robust workaround rather than refactoring the entire domain model improperly.
- [2026-01-27] **Testing**: `polyfactory` builds actual Pydantic models, not `MagicMock` objects. Dynamic attribute assignment (e.g., `signal._trail_updated = True`) will fail with `AttributeError` unless the model configuration allows extra fields. If a test relies on arbitrary attributes, manually patch the instance or use a mock instead.

### Type Hints & Recursion
- [2026-01-27] **Pydantic & Recursion**: When mapping nested Pydantic models to external schemas (e.g., BigQuery `RECORD`s), use explicit recursion. `issubclass(type, BaseModel)` works well for Pydantic V2, but be wary if V1 compatibility layers are introduced as they might not inherit cleanly.
- [2026-01-27] **Type Unwrapping**: Python's `typing.get_origin` and `get_args` are essential for unwrapping `Optional[T]`, `List[T]`, and `Union[T, None]`. However, complex Unions (e.g., `Union[int, float]`) require specific handling logic and generally default to a lowest-common-denominator strategy (e.g., string) if not explicitly mapped.
- [2026-01-29] **Type Hint Consistency**: When refactoring a function to return structured data (e.g., `List[str]` → `List[tuple[str, str]]`), update ALL return type annotations in the call chain. Forgetting helper methods causes mypy/pyright false errors and confuses code reviewers.

### Exception Handling & CI/CD
- [2026-01-29] **Silent Failures**: Never swallow exceptions in CLI tools without re-raising. `except Exception as e: logger.error(...)` without `raise` causes the script to exit with code 0, falsely reporting success in CI/CD pipelines.
- [2026-01-29] **Redundant Exception Handling**: `except (SpecificError, Exception)` is redundant since `Exception` catches everything. Either catch only the specific error for targeted handling, or just catch `Exception`. Mixing them adds no value and signals code smell to reviewers.

### BigQuery Schema Evolution
- [2026-01-29] **ALTER TABLE Multi-Column**: BigQuery supports adding multiple columns in a single `ALTER TABLE` statement with comma-separated `ADD COLUMN` clauses. This is more efficient than individual ALTER statements and ensures atomicity within BigQuery's eventual consistency.
- [2026-01-29] **Migration CLI Pattern**: For controlled schema evolution, create a CLI tool that: (1) validates schema drift with `strict_mode=False`, (2) generates DDL programmatically, (3) executes with proper error propagation. This avoids manual SQL and integrates with existing validation frameworks.

### Code Review Best Practices
- [2026-01-29] **Jules Delegation Review**: When reviewing work delegated to AI assistants (like Jules), focus on: (1) type safety / annotation consistency, (2) exception handling completeness, (3) test coverage for error paths. AI-generated code often handles happy paths well but may miss edge case handling and CI/CD implications.

### Broker API Constraints
- [2026-01-29] **Alpaca Notional Minimum**: Alpaca rejects orders with notional value below $1 (crypto) or $10 (equity). Use a safety buffer (e.g., $15) and validate BEFORE submitting to avoid API errors. Log the calculated notional value for debugging.
- [2026-01-29] **DRY Validation Pattern**: When the same validation logic applies across multiple execution paths (e.g., crypto vs equity), extract to a helper method immediately. Duplicated validation logic drifts over time and leads to inconsistent behavior.
- [2026-01-29] **Helper Method Naming**: For boolean validation helpers, use `_is_*_sufficient()` or `_has_*()` naming convention. This makes the condition readable in if-statements: `if not self._is_notional_value_sufficient(qty, signal)`.

### Discord API
- [2026-01-29] **Forum Channel Thread Requirement**: Discord Forum Channels (type 15) require `thread_name` in webhook payloads. Omitting it causes `400 Bad Request`. Add a config flag (e.g., `DISCORD_USE_FORUMS`) to conditionally include `thread_name`.
- [2026-01-29] **Module-Level Constants**: For sets used in multiple methods (e.g., `BULLISH_PATTERNS`), define as module-level `frozenset` to avoid duplication and enable O(1) lookups. This also makes the constant visible for import/testing.
- [2026-01-29] **Text Channel Fallback**: When posting to Discord with `thread_name` but the webhook targets a Text Channel (not Forum), Discord returns `400`. Implement retry logic that strips `thread_name` and retries for graceful degradation.

### Architecture & Patterns
- [2026-01-29] **Repository Pattern**: Always encapsulate Firestore access (e.g., `dim_strategies`) in a dedicated Repository class rather than using raw clients in pipelines. This ensures consistent error handling, centralized query logic, and significantly easier mocking in unit tests.
- [2026-01-29] **Merge Strategy**: When merging multiple concurrent feature branches (e.g., Metrics Fixes, Strategy Sync, Snapshot), carefully inspect central orchestration files like `main.py`. Automated merges often drop lines or duplicate logic blocks. Verify the presence of ALL features post-merge before running tests.

### Testing
- [2026-01-29] **Pydantic Mocking**: When unit testing logic that relies on Pydantic's `model_dump()`, mocking the model instance with `MagicMock` often fails because `model_dump` is a complex method. Use real Pydantic model instances in tests whenever possible to avoid "mock drift" where tests pass but runtime fails.
- [2026-01-29] **ExitStack Pattern**: When a test requires patching many dependencies (e.g., > 10) to isolate a "God Function" like `main()`, use `contextlib.ExitStack`. Standard nested `with patch():` blocks hit Python's stack limit (`SyntaxError: too many statically nested blocks`).
- [2026-01-29] **Pytest Config Override**: If `pyproject.toml` enforces strict plugins (like `pytest-cov`) that are failing in a specific environment, use `pytest -o "addopts=" ...` to override the configuration at runtime and isolate the test logic from the tooling environment.

### Deployment & Infrastructure
- [2026-01-30] **Container Permissions**: `joblib.Memory` creates a cache directory upon initialization. In restricted container environments (like Cloud Run), the application user often cannot write to the default location. Solved by initializing conditionally: `memory = joblib.Memory(location=None)` when caching is disabled. This prevents directory creation attempts during module import.
- [2026-01-30] **Bash Scripting**: When generating visual separators, `printf '%.0s=' {1..80}` is more portable and reliable than `echo "=" * 80` (which zsh handles but bash sometimes treats literally or requires loops).
- **Pydantic Defaults**: For conditional defaults based on other fields (e.g. `ENVIRONMENT`), use `default=None` and a `@model_validator` to set the value. Avoiding `default_factory` for simple env-based logic keeps the schema cleaner and validation more predictable.
- [2026-01-30] **Linting in Tests**: Test files (`tests/`) must adhere to the same linting standards as source code (including import sorting `I001`). `ruff check --fix` is essential before committing.
- [2026-01-30] **Pre-Commit Hooks**: If pre-commit hooks modify files (e.g., formatting), the commit fails. You must re-stage the modified files (`git add`) and commit again. `pre-commit run --all-files` is a good manual check before pushing.
- [2026-01-30] **Docker Env Files**: Docker's `--env-file` parser reads values literally and does NOT strip inline comments. A line like `VAR=val # comment` results in the value `"val # comment"`, causing Pydantic validation errors. Comments must be on their own lines.
- [2026-01-30] **CI/CD Validation**: When running container validation checks (e.g., `python -c "import main"`) in GitHub Actions, you must explicitly inject required environment variables (like `GOOGLE_CLOUD_PROJECT`) if the module initialization relies on strict Pydantic settings. Using `vars.GOOGLE_CLOUD_PROJECT` context is preferred.
- [2026-01-30] **Windows WSL**: On Windows, invoking `bash` from PowerShell may target a broken WSL distribution instead of Git Bash. Use the absolute path to the Git Bash executable (e.g., `& "C:\Program Files\Git\bin\bash.exe"`) for reliable script execution.

### BigQuery & Data Engineering
- [2026-01-30] **SQL Division**: BigQuery Standard SQL defaults to `FLOAT64` division (`/`). `SAFE_DIVIDE(x, y)` is useful for zero-safety but technically redundant in `GROUP BY` counts (guaranteed >= 1). However, defensive programming often prefers explicit safety.
- [2026-01-30] **Schema Management**: Avoid hardcoding BigQuery schemas in pipelines. Use `SchemaGuardian` (or similar utility) to dynamically generate schemas from Pydantic models. This ensures single source of truth and eliminates drift.

### Workflow & Git
- [2026-01-30] **Reverting Feedback**: When rejecting PR feedback that was partially applied, ensure specific commits are reverted cleanly. `git reset` or `git revert` is safer than manual edits which might miss artifacts (like stale comments).
- [2026-01-30] **Pre-Commit Formatting**: Tools like `ruff-format` modify files in place, causing git commits to fail. The remediation is to simply `git add` the modified files and retry the commit.
