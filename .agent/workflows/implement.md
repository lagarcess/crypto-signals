---
description: Turn issues into working code with a single command
---

1. **Strategic Planning**
   - Execute the `/plan` workflow.
   - Wait for user approval of `temp/plan/implementation-plan.md`.

2. **Branch Management**
   // turbo
   - Check if current branch is `main`. if so:
     - **Check Remote**: `git fetch origin`
     - **Check Linked Branch**: Check if a branch like `feat/123-desc` already exists remotely.
       - IF Exists: `git checkout [existing_branch]`
       - IF Not Exists: Create a new branch:
         - IF Issue Exists: `[type]/[issue_id]-[short-desc]`
         - IF No Issue: `[type]/[short-desc]`
   - **Type Selection**:
     - `feat`: New features
     - `fix`: Bug fixes
     - `refactor`: Code restructuring
     - `chore`: Maintenance/Docs
     - `perf`: Performance improvements

3. **Test-First Implementation**
   - Create new test files in `tests/` outlining the desired behavior (Red phase).
   - Ensure tests cover:
     - Happy paths.
     - Edge cases (error handling, invalid inputs).
     - Integration points (if applicable).

3. **Iterative Development**
   - Execute the `/tdd` workflow.
   - Loop: Write minimal code -> Run specific test -> Fix -> Repeat until PASS.

4. **Code Coverage Check**
   // turbo
   - Run coverage check: `$env:COVERAGE_FILE="temp/coverage/.coverage"; poetry run pytest --cov=src --cov-report=html:temp/coverage/html --cov-report=xml:temp/coverage/coverage.xml`
   - If coverage drops significantly, add missing test cases.

5. **Hygiene Pass**
   - Execute the `/cleanup` workflow to tidy up artifacts before final verification.
