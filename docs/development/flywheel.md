# AI Flywheel: The Triple-Agent Synergy

This project utilizes a high-velocity "flywheel" powered by three distinct AI entities: **Antigravity (IDE)**, **Gemini Code Assist (Reviewer)**, and **Jules (Autonomous Agent)**. This document outlines how they synchronize to maintain world-class engineering standards.

## 🔄 The Perfect Sync Model

Synchronization is driven by the **Repository-as-Source-of-Truth**. All tools share a common context derived from the following files:

| Tool | Role | Primary Context Sources |
| :--- | :--- | :--- |
| **Antigravity** | Human-Agent Interface | `temp/plan/implementation-plan.md` |
| **Jules** | Headless Execution Agent | `AGENTS.md`, `knowledge-base.md` |
| **Gemini** | Automated PR Reviewer | `gemini-reviewer-context.md` |

### Synchronization Lifecycle Triggers

1.  **`/plan` (IDE)**: Jules and Antigravity read the `knowledge-base.md` to ensure the new plan doesn't repeat past architectural mistakes.
2.  **`/verify` (Agent)**: Jules runs the full test suite and checks for environment isolation and JIT warmup.
3.  **PR Creation (Reviewer)**: Gemini Code Assist triggers. It validates the code against the "Staff Engineer" standards in `gemini-reviewer-context.md`.
4.  **`/learn` (Sync Momemnt)**: **Atomic Update**. Jules runs `/learn` post-merge to update the `knowledge-base.md`. No PR is considered complete without this step.

---

## 🛠 Self-Healing Loop

The flywheel includes an autonomous self-healing mechanism for continuous improvement:

1.  **Test Failure**: If `/verify` fails, it automatically triggers Jules to run `/fix`.
2.  **Autonomous Fix**: Jules patches the code and re-runs `/verify`.
3.  **Lesson Extraction**: After a successful fix, Jules runs `/learn` to extract the technical "gotcha" into the `knowledge-base.md`.
4.  **Mirroring**: If a safety rule changes, it must be updated in `AGENTS.md` (for Jules) AND `gemini-reviewer-context.md` (for Gemini).

---

## ⚡ Never-Violate Standards

To prevent "hallucination drift", we enforce these hard constraints:

- **Atomic Knowledge**: The `knowledge-base.md` is the only long-term memory.
- **Environment Parity**: `jules-setup.sh` ensures the VM matches the IDE environment exactly.
- **Two-Phase Commit**: Idempotency is enforced by persisting state BEFORE notifications.
- **TDD First**: Bug fixes must start with a failing test case in Jules's VM.

---

## 🔗 The "Staff Engineer" Anchor

The `gemini-reviewer-context.md` acts as the quality anchor. If you find a new design pattern or safety gap, update that file immediately. This ensures the automated reviewer stays as sharp as the human leads.
