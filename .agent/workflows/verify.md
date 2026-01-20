---
description: strict code review, system verifiction, and auto-commit
---

1. **System Health Check**
   // turbo
   - run the full test suite: `poetry run pytest`
   - run type checking (if applicable): `poetry run mypy src`
   - run linting: `poetry run ruff check src` (or equivalent).
   - run smoke test (Main Flow check):
     `python -m src.crypto_signals.main --smoke-test` (or `poetry run python -m src.crypto_signals.main --smoke-test`)
   - **On Failure**: Automatically trigger the `/fix` workflow to attempt self-correction.

2. **Deep Agent Review**
   - review the `git diff` of pending changes.
   - act as a "Senior Engineer" verifyer:
     - **Gap Analysis**: Are there missing edge cases?
     - **Security**: potentially unsafe operations?
     - **Scalability**: Any O(N^2) loops or heavy sync operations in async paths?
   - if issues are found, **fix them immediately** (do not ask, just fix, unless it requires design change).

3. **Pre-Commit Resolution**
   - attempt to commit: `git add . && git commit -m "feat: [description]"`
   - if pre-commit hooks fail (formatting, trailing whitespace, etc.):
     - resolve the specific hook errors.
     - re-add files and commit again.

4. **Final Success**
   - if commit succeeds, output: "✅ Verification passed and code committed."
