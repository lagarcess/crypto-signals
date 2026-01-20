---
description: Extract engineering lessons for future reference
---

1. **Knowledge Extraction**
   - Scan the `artifacts/IMPLEMENTATION_PLAN.md` and the git diff of the current branch.
   - Identify "Gotchas" or "Lessons Learned":
     - "API X requires Y format."
     - "Function Z is not thread-safe."
     - "Firestore index required for query A."

2. **Update Knowledge Base**
   - Append these lessons to `docs/KNOWLEDGE_BASE.md`.
   - Format: `- [Date] [Topic]: [Lesson]`
   - **Constraint**: Do not duplicate existing lessons.

3. **Commit**
   // turbo
   - `git add docs/KNOWLEDGE_BASE.md`
   - `git commit -m "docs: update knowledge base"`
