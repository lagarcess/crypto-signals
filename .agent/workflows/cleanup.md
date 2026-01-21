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
   - check if `README.md` or docstrings need updates based on recent changes.
   - update them if necessary to match the new code state.
