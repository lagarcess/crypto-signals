# Repository Instructions for AI Agents

This repository is a High-Frequency Crypto Trading System.
Precision, Idempotency, and Safety are the core values.

## 🛠 Build & Test Standards

### Development Environment
- **Package Manager**: Poetry (`poetry install`)
- **Linting**: Ruff (`poetry run ruff check src`)
- **Type Checking**: Mypy (`poetry run mypy src`)
- **Testing**: Pytest (`poetry run pytest`)

### Critical Workflows
- **Smoke Test**: `poetry run python -m src.crypto_signals.main --smoke-test`
- **JIT Warmup**: Run `src.crypto_signals.analysis.structural.warmup_jit()` before time-critical paths.

## 🏗 Architecture Overview
- `src/domain/`: Pure data classes (Signals, Patterns). No external IO.
- `src/repository/`: Firestore & Database interactions.
- `src/market/`: Data fetchers (Alpaca/CryptoData).
- `src/engine/`: Core logic (Signal Generator, Execution).
- `src/notifications/`: Discord integration.

## 🚨 Golden Rules
1. **Never mock `time.sleep` in live execution loops** (It messes up rate limiting).
2. **Always use Atomic Updates** for Firestore (`repo.update_signal_atomic`).
3. **Idempotency**: All notification and execution logic must be idempotent.
4. **Logs**: Use `loguru` with structured logging (extra={...}).
