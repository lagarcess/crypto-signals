---
description: Create a comprehensive Pull Request from current changes
---

1. **Final Verification**
   - Execute the `/verify` workflow.
   - If verification fails, **STOP** and report errors.

2. **Knowledge Capture**
   - Execute the `/learn` workflow to extract and save lessons from this session.

3. **Documentation & Knowledge Base Update**
   - Review `README.md`, `DEPLOYMENT.md`, and any files in `docs/`.
   - Update them to reflect:
     - New features or changed functionality.
     - Critical system behavior changes.
     - New configuration requirements.
   - **Privacy Check**: Ensure no sensitive internal logs or secrets are exposed in public docs.
   - Commit these documentation changes.

3. **PR Documentation Generation**
   - analyze the git diff and `artifacts/IMPLEMENTATION_PLAN.md`.
   - generate a PR Title and Description following this template:
     ```markdown
     ## Problem
     [Link to Issue #]
     [Description of the problem this PR solves]

     ## Solution
     [High-level technical approach]
     [Key architectural decisions]

     ## Changes
     - [File/Component]: [Change description]
     - [File/Component]: [Change description]

     ## Verification
     - [ ] Unit Tests passed
     - [ ] System checks passed
     - [ ] Manual verification step (if any)
     ```

3. **Branch & Push**
   // turbo
   - Create a new branch (if not already on one): `git checkout -b feat/issue-number-description`
   - Push changes: `git push origin HEAD`

4. **Submission**
   - Output the PR contents for the user to copy-paste into GitHub, or use `gh pr create` if the user has the CLI configured (ask first).
