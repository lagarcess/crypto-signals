# Engineering Knowledge Base
*Central repository of lessons learned, API quirks, and architectural gotchas.*

## General
- [2024-03-20] **Workflow**: Always run `/verify` before PR to catch regression.
- [2026-01-20] **Architecture**: Engines (`ExecutionEngine`) create domain objects but Repositories (`PositionRepository`) must persist them. Ensure orchestration layer bridges this gap.
- [2026-01-20] **Testing**: When mocking execution logic, ensure `ENVIRONMENT` settings match expected behavior (e.g., `PROD` + `ENABLE_EXECUTION=False` -> triggers Theoretical fallback).

## APIs & Integrations
### Alpaca
- [2024-XX-XX] **Orders**: Market orders during extended hours are rejected. Use Limit orders.
- [2026-01-20] **Typing**: Alpaca SDK v2 objects often need explicit casting (e.g., `cast(Order, response)`) to satisfy Mypy strict checks, especially when accessing `status` or `id` on union types.

### Firestore
- [2024-XX-XX] **Queries**: Composite queries require an index. Check logs for the creation link.

### GCP
- [2024-XX-XX] **Cloud Run**: Cold starts can exceed 10s. JIT warmup is essential.
