# The Crypto Sentinel AI Agency Blueprint

**Vision**: Transition from a single "Smart Assistant" to a structured "Team of Experts." As the sole human Staff Engineer, you manage a team of specialized AI personas that interact through strict contracts (Workflows, Rules, Skills) specifically tailored to build a scalable, free-tier GCP algorithmic trading and backtesting platform.

---

## 🏗️ 1. The Expert Personas (Skills & Roles)

Every agent interaction is framed by a Persona. When you prompt the system, the routing workflow determines *who* is answering.

### Core Engineering Pod (The Builders)
*   **The Backend Architect**: Focuses on Python, Pydantic, Domain-Driven Design, and GCP Cloud Run constraints.
*   **The Quantitative Researcher (Quant)**: Focuses strictly on math. Their job is Alpha generation, statistical drift analysis, and ensuring backtesting has zero look-ahead bias. They write pure numpy/pandas.
*   **The Database Reliability Engineer (DRE)**: Focuses on Firestore composite indexes, atomic batches, and BigQuery ETL syncs. They optimize for **GCP Free Tier limits** (minimizing read/writes).
*   **The Trading Execution Specialist**: Focuses strictly on Alpaca integration, rate limit handling, and the Signal State Machine.

### Product & Frontend Pod (The Visionaries)
*   **The Product Owner**: Focuses on the "Why." Before any code is written, this persona interrogates you about the business requirement. What are we trying to prove with this backtest? What data does the trader actually need to see?
*   **The UI/UX Prototyper**: Translates your Google Stitch drafts and Product Owner requirements into React/Next.js/Flutter code. Focuses on state management (Zustand/Redux) and responsive visualization of financial time-series data.

---

## 🚦 2. The Orchestration Workflows (Slash Commands)

To prevent AI chaos, work is routed through semantic, intuitive workflows. You act as the Staff Engineer approving handoffs between these experts.

### The "Managerial" Hand-offs
*   **`/kickoff`** (Replaces `/epic`): The **Product Owner** gathers requirements from you. Outputs a `requirements.md`.
*   **`/design`**: The **Backend Architect** and **DRE** read `requirements.md` and output an `rfc-design.md` (Request for Comment) detailing schema changes and API contracts. *You (Staff Engineer) approve this.*
*   **`/proto-sync`**: Takes exported code/designs from Google Stitch and translates them into the repository's frontend framework, ensuring the UI components map to the backend's Pydantic schemas.

### The "Execution" Pipelines (Already built!)
*   **`/plan` & `/implement`**: The coding loops.
*   **`/fix` & `/verify`**: The TDD and safety loops.
*   **`/sync`**: Multi-agent synchronization loop. Fetches upstream changes and performs strict infrastructure conflict resolution *before* reviews to prevent bot-merges from wiping out CI/CD.

---

## 🧠 3. The Future Analytics & ML Stack (Layered Complexity)

We do not decommission old layers; we build on them iteratively when the limit of the previous layer is reached. The **Quant** persona guides this evolution.

1.  **Layer 1: Structural Heuristics (Current)**
    *   *Tech*: Numba JIT, Pandas, simple math (SMA, RSI, Harmonics).
    *   *Goal*: Establish the execution pipeline and basic event-driven architecture.
2.  **Layer 2: Statistical & Probabilistic (Next)**
    *   *Tech*: Scikit-learn, XGBoost, Statsmodels.
    *   *Goal*: Moving from arbitrary thresholds (e.g., "RSI > 70") to probabilistic thresholds (e.g., "75% probability of mean reversion based on historical volatility regime").
3.  **Layer 3: Deep Predictive ML (Future)**
    *   *Tech*: TensorFlow/PyTorch, LSTMs for time-series forecasting.
    *   *Goal*: Predicting the $N$-step forward price curve rather than just reacting to historical lagging indicators.
4.  **Layer 4: Reinforcement Learning (Endgame)**
    *   *Tech*: Ray RLlib, custom gym environments.
    *   *Goal*: The agent learns the optimal execution strategy (when to limit vs market buy) to minimize slippage in real-time.

---

## ☁️ 4. GCP Free-Tier Infrastructure Scaling

The architecture is explicitly constrained by cost. The **Backend Architect** and **DRE** enforce these limits:

*   **Compute**: Cloud Run (scale-to-zero). We batch execution logic and exit gracefully to prevent idle billing. Only scale to Always-On when shifting from Paper Trading to Live HFT (High-Frequency Trading).
*   **Data Hot-tier**: Firestore (1GB free, 50k reads/day). Used ONLY for the *current state* (Open Positions, Active Signals).
*   **Data Cold-tier**: BigQuery (10GB free storage, 1TB free querying/month). Used for all historical tick data, closed signals, and backtesting. The `/migrate` workflow ensures data safely moves from Hot to Cold.
*   **Observability**: Cloud Logging (50GB free). Using `loguru` to generate structured JSON logs, exported via sink to BigQuery for cheap long-term forensic diagnosis.

---

## What's Next?
This blueprint maps the entire future state of your AI Agency. Whenever you are ready to tackle a new feature (like building the Frontend Backtesting Lab), we invoke `/kickoff` and let the Product Owner and UI Prototyper draft the contracts!
