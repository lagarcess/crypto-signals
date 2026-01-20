---
description: inner-loop TDD cycle with smart error correction
---

1. **Test Identification**
   - identify the test file corresponding to the active source file (typically in `tests/`).
   - if no test exists, propose creating one.

2. **Test Execution Loop**
   // turbo
   - run the specific test using poetry: `poetry run pytest tests/path/to/test_file.py`

   - **If Pass**:
     - Briefly check if the implementation is "meaningful" (not just a hardcoded bypass).
     - Stop and report success.

   - **If Fail**:
     - Analyze the error output.
     - Read the source code to understand *why* it failed.
     - **Critical Check**: Ensure the fix preserves system scalability and functionality (no hacky patches).
     - Apply the fix to the source code.
     - **Repeat Step 2**.

3. **Safety Valve**
   - if the loop fails more than 3 times, **STOP** and ask the user for guidance to avoid infinite loops.
