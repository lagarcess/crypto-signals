# Antigravity Workflow Guide

This guide outlines the autonomous engineering workflows configured for this project. These workflows are designed to maximize velocity, safety, and continuous learning.

## 🚀 The Golden Path (Order of Operations)

Follow this sequence for every standard task or issue.

| Phase | Command | Status | Description |
| :--- | :--- | :--- | :--- |
| **0. Health** | `/diagnose` | Optional | **Infrastructure Check**. Verifies GCP, Firestore, and Alpaca health. Run if you suspect environment issues. |
| **1. Plan** | `/plan [issue]` | **Required** | **The Architect**. Checks logs, validates bugs, reads `KNOWLEDGE_BASE`, and generates `temp/plan/implementation-plan.md`. Stops for user approval. |
| **2. Build** | `/implement` | **Required** | **The Builder**. Creates feature branch, writes **Tests First**, enters TDD Loop (`/tdd`), and performs hygiene (`/cleanup`). |
| **3. Verify** | `/verify` | **Required** | **The Auditor**. Full tests + Smoke Test + **Local Docker Pre-flight**. Auto-triggers `/fix`. |
| **4. Pre-Flight** | `/preflight` | Optional | **CI/CD Safety**. Docker build + GCP auth check to prevent remote failures. |
| **5. Ship** | `/pr` | **Required** | **The Publisher**. Captures lessons (`/learn`), updates docs, and triggers **Gemini Review**. |
| **6. Reset** | `/cleanup_branch` | Post-Merge | **The Janitor**. Switches to `main`, pulls latest, deletes branch. |

---

## 🛠 Command Details

### `/plan`
*   **Trigger**: Start of every new task.
*   **Actions**:
    - Forensics (Log analysis for bugs).
    - System Design Check (`../operations/deployment-guide.md`).
    - Knowledge Retrieval (Reads `./knowledge-base.md`).
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
    - **Trigger Review**: Activates **Gemini Code Assist** for high-standard PR review.
    - **Doc Sync**: Updates `README.md` with new features.
    - **Push**: Pushes branch to origin.
*   **Outcome**: A GitHub PR link followed by an automated review.

### `/preflight`
*   **Trigger**: Before `/pr` to ensure CI/CD stability.
*   **Actions**:
    - Build production container locally.
    - Run containerized smoke test.
    - Validate GCP project and connectivity.
*   **Outcome**: High confidence that `deploy.yml` will pass.

---

## ⚡ Shortcuts & Tips

*   **Chaining Commands**:
    > *"Run /implement then /verify"*
    > (Builds, tests, fixes, and verifies in one autonomous run.)

*   **Quick Fixes**:
    > *"Run /implement fix for typo in README then /pr"*
    > (Branches, fixes, verifies, and pushes in one go.)

## 🔗 Common Action Sequences (The Menu)

| Goal | Sequence | Description |
| :--- | :--- | :--- |
| **New Feature (Standard)** | `/plan` → `/implement` → `/review` → `/verify` → `/pr` | The full Golden Path. Safe, Architected, Verified. |
| **New Idea (Fast)** | `/plan [idea]` → `/implement` → `/pr` | For non-issue work. Agent auto-names branch. |
| **Bug Fix (Known)** | `/implement [fix]` → `/verify` → `/pr` | Skip planning if the fix is obvious. |
| **Code Polish** | `/cleanup` → `/review` → `/verify` | No logic change, just hygiene and refactoring. |
| **Dependabot/Upgrades** | `/implement [upgrade]` → `/verify` | Updating dependencies and ensuring tests pass. |
| **Infrastructure Fix** | `/diagnose` → `/fix` | Check cloud health and attempt auto-patching. |
| **Post-Merge Reset** | `/cleanup_branch` | Switch to main, pull, delete old branch. |

*   **Manual Overrides**:
    - **`/fix`**: Run manually if you see a test failure you want the agent to patch immediately.
    - **`/cleanup`**: Run manualy to tidying up dead code/TODOs without running a full verification.

## 🧠 Knowledge Base (`./knowledge-base.md`)
This file is the **Long-Term Memory** of the project.
*   It is updated automatically by `/pr` (via `/learn`).
*   It is read automatically by `/plan`.
*   **Goal**: Stop making the same mistake twice.

## 🔄 AI Flywheel Synergy
This project uses a triple-agent model to ensure quality:
- **Antigravity (IDE)**: Your primary workbench.
- **Jules (VM)**: Your autonomous execution agent (configured via `AGENTS.md`).
- **Gemini (Reviewer)**: Your Staff Engineer gatekeeper (configured via `gemini-reviewer-context.md`).
- **Sync**: All tools are synced via the **Repository-as-Source-of-Truth** model. See **[AI Flywheel Guide](flywheel.md)**.
