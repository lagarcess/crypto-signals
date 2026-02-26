---
description: Audits the repository and synchronizes all documentation (.md files, docstrings) with the current codebase state.
---

**Context**: You noticed that documentation (`docs/`, `AGENTS.md`, docstrings) can easily drift as code rapidly evolves. The `/sync-docs` workflow is the system's "immune response" against technical debt. It forces the AI to cross-reference reality against the written word.

1.  **Architecture vs. Reality Audit**
    - Read `.agent/agency_blueprint.md` and `AGENTS.md`.
    - Verify that all mentioned tools, constraints, and personas actually exist in the `.agent/` directories or `scripts/`.
    - If a feature is documented but missing, flag it as a hallucination or dead link.

2.  **Design Contract Synchronization**
    - Review `docs/designs/rfc-design.md` or `knowledge-base.md`.
    - Cross-reference the documented Python classes/types against the actual `src/crypto_signals/` implementations.
    - Has a Pydantic schema evolved but the design doc still reflects the old version? Fix the design doc.

3.  **Actionable Output**
    - **Hard Fixes**: Directly edit markdown files (`docs/**/*.md`, `AGENTS.md`, etc.) to match the code truth.
    - **Report**: Output a checklist of what was out-of-sync and what was updated.
    - "✅ Documentation and Agency Workflows are fully synchronized with the codebase."
