---
description: AI Code Review (Staff Engineer Persona) + Hygiene Pass
---

1.  **Diff Analysis & Automated Cleanup**
    - Capture the changes: `git diff main...HEAD`.
    - Compare against `temp/plan/implementation-plan.md` (if exists).
    - **Hygiene Pass (Pre-Review)**: Scan for dead code, resolved TODOs, and AI reasoning markers (like "I'll now...", "As an AI..."). Replace them with concise engineering notes and remove the dead code.

2.  **Existing PR Comments Analysis**
    - Fetch inline comments (if PR exists).
    - Parse logs, identify unresolved requests for changes or High Priority feedback.

3.  **Semantic Critique**
    - Analyze the code against "Staff Engineer" standards.
    - **Readability**: Are variable names descriptive? Are magic numbers used?
    - **Complexity**: Identify nested loops > 3 levels or functions > 50 lines.
    - **Architecture**: Does logic leak between layers? Does Domain have IO?
    - **Security**: Specific check for injections or hardcoded secrets.
    - *Constraint*: Do NOT report simple styling issues (handled by pre-commit hooks during `/verify`).

4.  **Report Generation & Fix**
    - Generate a "Review Report" markdown artifact into `temp/review/review-report.md`.
    - Present the report. Auto-fix critical issues immediately. For subjective suggestions, ask the user.
