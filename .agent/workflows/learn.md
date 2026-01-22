---
description: Extract engineering lessons for future reference
---

1. **Knowledge Extraction**
   - Scan the `temp/plan/implementation-plan.md` and the git diff of the current branch.
   - Identify "Gotchas" or "Lessons Learned":
     - "API X requires Y format."
     - "Function Z is not thread-safe."
     - "Firestore index required for query A."

2. **Update Knowledge Base**
   - Append these lessons to `docs/development/knowledge-base.md`.
   - Format: `- [Date] [Topic]: [Lesson]`
   - **Constraint**: Do not duplicate existing lessons.

3. **Commit**
   // turbo
   - `git add docs/development/knowledge-base.md`
   - `git commit -m "docs: update knowledge base"`
