---
description: Recursive self-correction loop for test failures
---

1. **Analyze Failure**
   - Read the output of the failed test or lint command.
   - Identify the specific error (e.g., "AssertionError", "ImportError", "Timeout").

2. **Self-Correction Loop (Max 3 Attempts)**
   // turbo
   - **Attempt 1**:
     - Locate the source code causing the error.
     - Apply a fix based on the error message.
     - Re-run the specific failing test.
     - If PASS -> Stop and Report Success.
   - **Attempt 2 (if 1 fails)**:
     - Read the new error message (did it change?).
     - Check `docs/KNOWLEDGE_BASE.md` for similar past issues.
     - Apply a different fix.
     - Re-run the test.
     - If PASS -> Stop.
   - **Attempt 3 (if 2 fails)**:
     - Re-read the `IMPLEMENTATION_PLAN.md` to ensure we aren't violating the design.
     - Try a fundamental correction.
     - Re-run the test.

3. **Escalation**
   - If Attempt 3 fails:
     - **STOP**.
     - Report: "Unable to auto-fix. Manual intervention required."
     - Show the last error log.
