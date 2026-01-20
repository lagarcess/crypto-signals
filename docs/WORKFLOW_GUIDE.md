# Antigravity Workflow Guide

This guide outlines the autonomous engineering workflows configured for this project. These workflows are designed to maximize velocity, safety, and continuous learning.

## 🚀 The Golden Path (Order of Operations)

Follow this sequence for every standard task or issue.

| Phase | Command | Status | Description |
| :--- | :--- | :--- | :--- |
| **0. Health** | `/diagnose` | Optional | **Infrastructure Check**. Verifies GCP, Firestore, and Alpaca health. Run if you suspect environment issues. |
| **1. Plan** | `/plan [issue]` | **Required** | **The Architect**. Checks logs, validates bugs, reads `KNOWLEDGE_BASE`, and generates `IMPLEMENTATION_PLAN.md`. Stops for user approval. |
| **2. Build** | `/implement` | **Required** | **The Builder**. Creates feature branch, writes **Tests First**, enters TDD Loop (`/tdd`), and performs hygiene (`/cleanup`). |
| **3. Verify** | `/verify` | **Required** | **The Auditor**. Runs full test suite + Smoke Test. **Auto-triggers `/fix` on failure** (Self-Healing). Auto-commits on success. |
| **4. Ship** | `/pr` | **Required** | **The Publisher**. Captures lessons (`/learn`), updates `README`/Docs, writes PR description, and pushes branch. |
| **5. Reset** | `/cleanup_branch` | Post-Merge | **The Janitor**. Switches to `main`, pulls latest, and deletes the local feature branch. |

---

## 🛠 Command Details

### `/plan`
*   **Trigger**: Start of every new task.
*   **Actions**:
    - Forensics (Log analysis for bugs).
    - System Design Check (`DEPLOYMENT.md`).
    - Knowledge Retrieval (Reads `docs/KNOWLEDGE_BASE.md`).
*   **Outcome**: A solid plan tailored to the architecture.

### `/implement`
*   **Trigger**: After plan approval.
*   **Actions**:
    - **Branch Safety**: Forces creation of `feat/XYZ` branch.
    - **TDD**: Writes failing tests -> Writes Code -> Fixes.
*   **Outcome**: Working code that passes local tests.

### `/verify`
*   **Trigger**: Before considering code "done".
*   **Actions**:
    - Run `pytest`, `ruff`, `mypy`.
    - Run `python -m src.crypto_signals.main --smoke-test`.
    - **Self-Correction**: If any step fails, triggers `/fix` recursively (Max 3 attempts).
    - **Deep Agent Review**: Checks for Security/Scalability gaps.
*   **Outcome**: A verified, signed-off commit.

### `/pr`
*   **Trigger**: Ready to merge.
*   **Actions**:
    - **Institutional Memory**: Runs `/learn` to update Knowledge Base.
    - **Doc Sync**: Updates `README.md` with new features.
    - **Push**: Pushes branch to origin.
*   **Outcome**: A GitHub PR link.

---

## ⚡ Shortcuts & Tips

*   **Chaining Commands**:
    > *"Run /implement then /verify"*
    > (Builds, tests, fixes, and verifies in one autonomous run.)

*   **Quick Fixes**:
    > *"Run /implement fix for typo in README then /pr"*
    > (Branches, fixes, verifies, and pushes in one go.)

*   **Manual Overrides**:
    - **`/fix`**: Run manually if you see a test failure you want the agent to patch immediately.
    - **`/cleanup`**: Run manualy to tidying up dead code/TODOs without running a full verification.

## 🧠 Knowledge Base (`docs/KNOWLEDGE_BASE.md`)
This file is the **Long-Term Memory** of the project.
*   It is updated automatically by `/pr` (via `/learn`).
*   It is read automatically by `/plan`.
*   **Goal**: Stop making the same mistake twice.
