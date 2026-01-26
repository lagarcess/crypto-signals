# Project Agents & Tools: Crypto Sentinel

This file provides a map of the core modules, responsibilities, and constraints for autonomous agents (Jules) and AI tools.

## Key Modules & Responsibilities

| Component | Path | Responsibility | Constraints |
| :--- | :--- | :--- | :--- |
| **Domain** | `src/crypto_signals/domain/` | Pydantic schemas and core logic. | **Zero External IO**. Pure logic/data only. |
| **Engine** | `src/crypto_signals/engine/` | Orchestration (Signal, Execution, Reconciler). | Must bridge Domain and Repository layers. |
| **Repository** | `src/crypto_signals/repository/` | Persistence layer (Firestore). | Must handle composite index requirements. |
| **Analysis** | `src/crypto_signals/analysis/` | Technical indicators & pattern detection. | **Numba JIT Requirement**. Must include warmup tests. |
| **Market** | `src/crypto_signals/market/` | API wrappers (Alpaca). | Defensive parsing. Strict 404 handling. |
| **Pipelines** | `src/crypto_signals/pipelines/` | BigQuery ETL & Archival logic. | Schema parity checks required. |

## Core Commands (Slash Commands)

Jules should use these commands to ensure synchronization with the developer workflow.
**Definition Source**: The detailed steps for each command are defined in the `.agent/workflows/` directory.

- `/plan [task]`: Generates `temp/plan/implementation-plan.md`. Always starts here.
- `/implement`: Enters TDD loop. Writes tests first.
- `/verify`: Runs full test suite + Smoke Test + Local Docker Pre-flight.
- `/preflight`: **NEW**. Local check (Docker + GCP) to catch CI failures before push.
- `/learn`: **Critical**. Updates `docs/development/knowledge-base.md` with new findings. Run after every major change.
- `/diagnose`: Includes **CI/CD Forensics** via `gh` CLI.
- `/fix`: Recursive self-correction loop for test failures.
- `/review-jules`: **Manager Mode**. Delegate feedback to Jules via `post_review.py`.

## Never-Violate Standards

1. **Environment Isolation**: Never override `ENVIRONMENT=PROD` in automated scripts. Use `DEV` or `STAGING` for fixes.
2. **Two-Phase Commit**: Always persist a signal or state to Firestore *before* sending a Discord notification.
3. **JIT Warmup**: Any changes to `analysis/structural.py` require a `warmup_jit()` call to prevent latency spikes in production.
4. **Structured Logging**: Use `loguru` with context (`signal_id`, `symbol`). No standard `print` statements.
5. **TDD First**: Generate a failing test for bugs before writing the fix.
6. **Doc Parity**: Root files (e.g., `README.md`, `AGENTS.md`) must be in sync with the detailed wiki in `./docs`. Updates to systems must be propagated to both.
7. **Refactoring Rule**: If you extract logic into a new class/module, you **MUST** create a dedicated test file for it immediately. Do not rely on existing integration tests to cover new units.

## Synchronous Handover
- After a task is finished, run `/learn` to update the global knowledge base.
- Gemini Code Assist will review PRs against the standards defined here and in `.github/gemini-reviewer-context.md`.
