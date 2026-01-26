---
description: Manager-level review for delegations to Jules (Intern Persona)
---

**Context**: Use this workflow when reviewing PRs submitted by **Jules** (or other junior agents). The goal is to provide high-context, instructional feedback that triggers Jules' "Reactive Mode".

1.  **Analyze the Work**
    - **Fetch Context**: `gh pr view [pr_number]`
    - **Diff Check**: `git diff main...HEAD`
    - **Comment Check**: `poetry run python scripts/parse_pr_comments.py temp/output/pr_comments.json`
      - *Check if Jules missed any previous feedback.*

2.  **Generate Review Strategy (The "Manager" Persona)**
    - Does the code meet the *exact* requirements of the task?
    - Are there "Junior Mistakes"? (e.g., missing tests, hardcoded values, logic gaps).
    - **Action**: Draft a review JSON payload in `temp/review/jules_review.json`.

    **JSON Format Requirement**:
    ```json
    {
        "body": "## Manager Review\n\nJules, you missed X. Please fix Y...",
        "comments": [
            {
                "path": "src/file.py",
                "line": 10,
                "body": "Please extract this magic number to a constant named `MAX_RETRIES`."
            }
        ]
    }
    ```

3.  **Execute Review**
    - **Post Feedback**:
      `poetry run python scripts/post_review.py [pr_number] temp/review/jules_review.json --request-changes`
    - **Verify**: Check the PR link output provided by the script.

4.  **Handover**
    - Once posted, Jules will receive the notification as if it came from the User.
    - Wait for Jules to push fixes.
