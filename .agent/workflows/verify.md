---
description: strict code review, system verification, and auto-commit
---

**Setup**: Ensure directory exists: `if (!(Test-Path "temp/verify")) { New-Item -ItemType Directory -Path "temp/verify" -Force }`

1. **System Health Check**
   // turbo
   - **CRITICAL**: Run the **FULL** test suite: `poetry run pytest`
   - **Coverage Check**: Ensure coverage meets threshold (63%): `$env:COVERAGE_FILE="temp/coverage/.coverage"; poetry run pytest --cov=src --cov-report=html:temp/coverage/html --cov-report=xml:temp/coverage/coverage.xml`
   - run type checking (if applicable): `poetry run mypy src`
   - run linting: `poetry run ruff check src` (or equivalent).
   - run smoke test (Main Flow check):
     `python -m src.crypto_signals.main --smoke-test` (or `poetry run python -m src.crypto_signals.main --smoke-test`)
   - **Doc Parity**: Verify root-vs-wiki synchronization: `poetry run python scripts/verify_doc_parity.py`
   - **On Failure**: Automatically trigger the `/fix` workflow to attempt self-correction.
     - *Note*: If coverage is below 63%, Use `/fix` to identify untested paths and add tests.

   - **Local CD Pre-Flight (Docker)**
     - **Trigger**: Only if logic changes affecting production occur.
     - Build production image: `docker build -t crypto-signals:verify .`
     - Run containerized smoke test:
       ```bash
       docker run --rm -e DISABLE_SECRET_MANAGER=true -e ENVIRONMENT=DEV crypto-signals:verify python -m crypto_signals.main --smoke-test
       ```
     - **CRITICAL**: If container build or smoke test fails, the PR is **blocked**. Run `/fix`.


2. **Deep Agent Review**
   - review the `git diff` of pending changes.
   - act as a "Senior Engineer" verifyer:
     - **Gap Analysis**: Are there missing edge cases?
     - **Security**: potentially unsafe operations?
     - **Scalability**: Any O(N^2) loops or heavy sync operations in async paths?
   - if issues are found, **fix them immediately** (do not ask, just fix, unless it requires design change).

3. **Pre-Commit Hook Execution & Resolution**
   - **Branch Guard**:
     ```powershell
     $currentBranch = git branch --show-current
     if ($currentBranch -eq 'main') {
         Write-Error "CRITICAL: You are on 'main'. Please run /implement first to create a feature branch."
         return
     }
     ```

   - attempt to commit: `git add . && git commit -m "feat: [description]"`
   - **CAPTURE OUTPUT**: Save full pre-commit hook output with exit code
   - **If ALL hooks pass (exit code 0)**:
     - Output: "✅ Pre-commit hooks passed. Commit successful."
     - Proceed to step 4 (Final Success)
   - **If pre-commit hooks fail (exit code != 0)**:
     - **READ THE OUTPUT**: Parse all failure messages (trim whitespace, ruff violations, end-of-file fixes, etc.)
     - **CLASSIFY**: Identify if auto-fixable (ruff format, end-of-file-fixer) or manual-fix (logic errors)
     - **AUTO-FIXABLE**: Run hook-suggested commands (e.g., `poetry run ruff format .`)
     - **MANUAL-FIX**: If hook indicates manual code changes needed, run `/fix` workflow
     - **RETRY**: `git add .` and `git commit` again
     - **MAX RETRIES**: If fails 3 times, stop and escalate with hook output
     - **REPORT ALL**: Show each hook result (passed/failed) to user before next step
     - **LOOP**: Repeat until commit succeeds or escalation triggered

4. **Final Success**
   - if commit succeeds, output: "✅ Verification passed and code committed. All hooks passed."
   - if escalation triggered, output: "⚠️ Pre-commit hooks failed after 3 retries. Manual intervention required." + show hook output
