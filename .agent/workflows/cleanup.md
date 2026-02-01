---
description: code hygiene and clarity pass before final review
---

**PRE-CLEANUP NOTE**: This workflow removes dead code and TODOs. After cleanup is complete, run `/verify` workflow to ensure pre-commit hooks pass (hooks will detect any trailing whitespace, file formatting, etc. that cleanup may have introduced).

1. **Static Analysis**
   - scan the recently edited files.
   - look for:
     - Commented-out dead code.
     - `TODO` comments that have been resolved.
     - Redundant import statements (that linters might have missed).
     - Overly complex functions that could be simplified without changing logic.

2. **Hygiene Action**
   - remove the dead code and resolved TODOs.
   - **Constraint**: Do NOT refactor logic just for the sake of "cleverness".
   - **Rule**: "If it works and is simple enough, don't change it."

3. **Documentation Update**
   - Check these key documentation files for consistency with code changes:
     - `README.md` - Project structure, commands, environment variables
     - `docs/README.md` - Wiki hub links
     - `docs/development/scripts-organization.md` - Scripts and diagnostics
     - `docs/operations/infrastructure-health.md` - Health check commands
     - `.agent/workflows/*.md` - Workflow file paths and commands
   - Verify documentation reflects:
     - Current folder structure (especially `temp/`, `scripts/`, `src/crypto_signals/scripts/`)
     - Correct command paths (e.g., `python -m crypto_signals.scripts.diagnostics.*`)
     - Accurate workflow folder references (issues/, plan/, pr/, review/, verify/, etc (it evolves, keep it organized and intuitive))
   - **Consistency Check**: Ensure all docs show the same folder structure for `temp/`
   - **Auto-Sync**: Run `poetry run sync-docs` to ensure schemas are up-to-date.
   - Update if necessary to match the new code state.

4. **AI Reasoning Sanitization**
   - **Instruction**: Scan for "stream-of-consciousness" or "reasoning markers" in comments (e.g., "I am choosing this...", "Since we are...", "As an AI...").
   - **Action**: Replace them with concise engineering notes (e.g., "Refactored for scalability") or remove them if they don't explain the *what* or *why*.
   - **Scan Patterns**: Search for `We need to`, `I'll now`, `This approach`, `Let me check` in code comments.
