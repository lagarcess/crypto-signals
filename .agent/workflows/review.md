---
description: AI Code Review (Staff Engineer Persona) to replace Github Copilot
---

1.  **Diff Analysis**
    - Capture the changes: `git diff main...HEAD` (or `git diff HEAD~1` if fast-forward).
    - Read `temp/plan/implementation-plan.md` (if exists) to check alignment with the plan.

2.  **Existing PR Comments Analysis**
    - Fetch inline comments (if PR exists):
      `gh api repos/:owner/:repo/pulls/:pr_number/comments > temp/output/pr_comments.json`
      *Note: You may need to infer owner/repo or use `gh pr list` to get the PR number.*
    - Parse comments: `python scripts/parse_pr_comments.py temp/output/pr_comments.json`
    - **Review Goal**: Check `temp/output/pr_comments_readable.txt`. Identify any unresolved requests for changes or "High Priority" inline comments that haven't been addressed in the code.

3.  **Semantic Critique**
    - Analyze the code against "Staff Engineer" standards:
        - **Readability**: Are variable names descriptive? Are magic numbers used?
        - **Complexity**: Identify nested loops > 3 levels or functions > 50 lines.
        - **Functionality**: Check how the change works with the codebase
        - **Architecture**: Does logic leak between layers (e.g., Persistence logic in Domain)?
        - **Security**: Specific check for injections or hardcoded secrets.
    - **Constraint**: Do NOT report styling issues (handled by Ruff/Lint). Focus on Logic/Design.

3.  **Report Generation**
    - Ensure directory exists: `if (!(Test-Path "temp/review")) { New-Item -ItemType Directory -Path "temp/review" -Force }`
    - Generate a "Review Report" markdown artifact. If there are critical issues and suggestions, then explain what must change with reasoning behind it.
    - Save to `temp/review/review-report.md` (gitignored).
    - Format:
        ```markdown
        ## Code Review Report
        **Score**: [1-10]

        ### 🔴 Critical Issues
        - [File:Line]: Description

        ### 🟡 Suggestions
        - [File:Line]: Description
        ```

4.  **Interactive Improvement**
    - Present the report to the user.
    - **STOP** and ask: "Do you want me to apply these suggestions?"
    - **If YES**:
        - Apply the fixes.
        - Run `/verify` to ensure no regression.
    - **If NO**:
        - Exit workflow.
