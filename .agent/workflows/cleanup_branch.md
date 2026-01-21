---
description: Post-merge cleanup workflow
---

1. **Local Cleanup**
   // turbo
   - Switch to main: `git checkout main`
   - Pull latest changes: `git pull origin main`
   - Delete the local feature branch (if applicable, ask user for branch name or infer from previous context).
     `git branch -d [branch_name]` (use -D if not fully merged locally but confirmed merged remotely).
   - Prune remote branches: `git fetch --prune`
   - Clean up temporary files: `rm temp/*` (or `del temp\*` on Windows). Keep the directory, just empty contents.

2. **Environment Refresh**
   - Update dependencies: `poetry install` (if `pyproject.toml` changed).
   - Notify user: "System is clean, updated, and ready for the next task."
