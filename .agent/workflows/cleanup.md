---
description: code hygiene and clarity pass before final review
---

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
