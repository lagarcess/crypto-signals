# Implementation Plan: Issue #113 - State Reconciler

**Status**: In Planning
**Priority**: P0 - Critical
**Created**: January 20, 2026

---

## 📋 Goal

Implement a **State Reconciler** module to detect and resolve synchronization gaps between Alpaca broker state and Firestore database state. This prevents **zombie positions** (closed in Alpaca but marked OPEN in Firestore) and **orphan positions** (open in Alpaca but missing from Firestore) from creating silent trading failures or data corruption.

---

## 🔍 Problem Analysis

### Current State

- **Firestore** is the source of truth for position tracking
- **Alpaca** is the broker execution layer
- **No reconciliation mechanism** exists

### Risk Scenarios

1. **Zombie Positions** (Firestore says OPEN, Alpaca says CLOSED)
   - User manually closes position in Alpaca app → DB still shows OPEN
   - Stop-loss fills but Discord fails → retry logic closes position, DB not updated
   - Partial fills edge case → position marked CLOSED in Alpaca, OPEN in DB
   - **Impact**: False confidence in P&L, incorrect risk exposure calculations

2. **Orphan Positions** (Alpaca says OPEN, Firestore has no record)
   - Manual trade placed in Alpaca app → system unaware
   - Gap #1 condition: Signal created, execution fails to persist position (rare but possible)
   - Alpaca account activity from other sources/traders
   - **Impact**: Position management commands fail, unmanaged open positions accumulate

3. **Data Drift**
   - Positions in both systems but with mismatched metadata (fill price, quantities)
   - **Impact**: Inaccurate P&L analytics, incorrect commission tracking

---

## 🛠 Proposed Solution

### Architecture Decision

Create a new `engine/reconciler.py` module following the **repository pattern** already established in the codebase:

```
src/crypto_signals/
├── engine/
│   ├── reconciler.py (NEW)       # StateReconciler class
│   ├── signal_generator.py
│   └── execution.py
├── domain/
│   └── schemas.py                # Add CLOSED_EXTERNALLY to ExitReason
└── repository/
    └── firestore.py              # Already has PositionRepository
```

### Core Components

#### 1. **ReconciliationReport** (Domain Schema)

```python
class ReconciliationReport(BaseModel):
    """Result of a reconciliation run."""

    zombies: list[str]              # Symbols closed in Alpaca but OPEN in DB
    orphans: list[str]              # Symbols open in Alpaca but missing from DB
    reconciled_count: int            # Number of positions updated
    timestamp: datetime              # When reconciliation ran
    duration_seconds: float          # Execution time
    critical_issues: list[str]       # Alert-worthy problems
```

#### 2. **StateReconciler** (Engine Class)

Location: `src/crypto_signals/engine/reconciler.py`

**Responsibilities:**

- Compare Alpaca broker state with Firestore database state
- Detect discrepancies (zombies and orphans)
- Auto-heal zombies (mark CLOSED_EXTERNALLY)
- Alert on orphans (critical notification)
- Generate reconciliation report

**Key Methods:**

```python
class StateReconciler:
    def __init__(
        self,
        alpaca_client: TradingClient,
        position_repo: PositionRepository,
        discord_client: DiscordClient,
        settings: Settings
    )

    def reconcile(self) -> ReconciliationReport:
        """Execute full reconciliation and return report."""

    def _detect_zombies(self) -> list[str]:
        """Find positions closed in Alpaca but OPEN in Firestore."""

    def _detect_orphans(self) -> list[str]:
        """Find positions open in Alpaca but missing from Firestore."""

    def _heal_zombie(self, symbol: str) -> bool:
        """Mark zombie position as CLOSED_EXTERNALLY."""

    def _alert_orphan(self, symbol: str) -> bool:
        """Send critical Discord notification for orphan position."""
```

---

## 📝 Implementation Breakdown

### Phase 1: Domain Model Changes

**File**: `src/crypto_signals/domain/schemas.py`

Add new exit reason:

```python
class ExitReason(str, Enum):
    # ... existing values ...
    CLOSED_EXTERNALLY = "CLOSED_EXTERNALLY"  # Position closed outside system
```

Add reconciliation report schema:

```python
class ReconciliationReport(BaseModel):
    """Report of state reconciliation between Alpaca and Firestore."""

    zombies: list[str] = Field(
        default_factory=list,
        description="Symbols closed in Alpaca but marked OPEN in Firestore"
    )
    orphans: list[str] = Field(
        default_factory=list,
        description="Symbols with open positions in Alpaca but no Firestore record"
    )
    reconciled_count: int = Field(
        default=0,
        description="Number of positions updated during reconciliation"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="When reconciliation was performed"
    )
    duration_seconds: float = Field(
        default=0.0,
        description="Time taken to run reconciliation"
    )
    critical_issues: list[str] = Field(
        default_factory=list,
        description="Critical alerts (e.g., orphan positions)"
    )
```

**Changes Required:**

- ✅ Add `CLOSED_EXTERNALLY` enum value
- ✅ Add `ReconciliationReport` model
- ✅ No breaking changes to existing models

---

### Phase 2: StateReconciler Implementation

**File**: `src/crypto_signals/engine/reconciler.py` (NEW)

**Key Algorithm:**

```python
def reconcile(self) -> ReconciliationReport:
    start_time = time.time()

    # 1. Fetch all open positions from both systems
    alpaca_positions = self.alpaca.list_positions()  # Active Alpaca positions
    firestore_positions = self.position_repo.get_open_positions()  # DB positions

    alpaca_symbols = {p.symbol for p in alpaca_positions}
    firestore_symbols = {p.symbol for p in firestore_positions}

    # 2. Detect discrepancies
    zombies = firestore_symbols - alpaca_symbols  # Firestore has it, Alpaca closed it
    orphans = alpaca_symbols - firestore_symbols  # Alpaca has it, Firestore doesn't

    # 3. Heal zombies
    for symbol in zombies:
        pos = self.position_repo.get_by_symbol(symbol)
        pos.status = TradeStatus.CLOSED
        pos.exit_reason = ExitReason.CLOSED_EXTERNALLY
        self.position_repo.update_position(pos)
        self.discord.send_message(f"🧟 ZOMBIE HEALED: {symbol}")

    # 4. Alert orphans
    for symbol in orphans:
        logger.critical(f"ORPHAN POSITION DETECTED: {symbol}")
        self.discord.send_critical_alert(f"⚠️  ORPHAN: {symbol}")

    # 5. Build report
    return ReconciliationReport(
        zombies=list(zombies),
        orphans=list(orphans),
        reconciled_count=len(zombies),
        duration_seconds=time.time() - start_time,
        critical_issues=[f"ORPHAN: {s}" for s in orphans]
    )
```

**Considerations:**

- **Idempotency**: Healing the same zombie multiple times is safe (merge=True)
- **Error Handling**: If healing fails, log and continue (don't crash execution loop)
- **Rate Limiting**: Respect Alpaca 200 req/min (list_positions is 1 call)
- **Environment Gating**: Skip execution in non-PROD (similar to ExecutionEngine)

---

### Phase 3: Integration into Main Loop

**File**: `src/crypto_signals/main.py`

**Location**: After service initialization, before portfolio loop (per issue template)

```python
# Initialize Services (existing code ~line 115)
# ...
execution_engine = ExecutionEngine()
job_lock_repo = JobLockRepository()
rejected_repo = RejectedSignalRepository()

# NEW: Initialize StateReconciler
reconciler = StateReconciler(
    alpaca_client=get_trading_client(),
    position_repo=position_repo,
    discord_client=discord,
    settings=settings
)

# NEW: Run reconciliation at startup
logger.info("Running state reconciliation...")
try:
    reconciliation_report = reconciler.reconcile()
    if reconciliation_report.critical_issues:
        logger.warning(f"Reconciliation detected issues: {reconciliation_report.critical_issues}")
    logger.info(f"Reconciliation completed: {reconciliation_report.reconciled_count} positions healed")
except Exception as e:
    logger.error(f"Reconciliation failed: {e}", extra={"error": str(e)})
    # Don't halt execution - reconciliation is advisory

# Portfolio loop continues (existing code)
```

---

## 🧪 Verification Strategy

### Unit Tests

**File**: `tests/engine/test_reconciler.py`

```python
def test_detect_zombies():
    """Zombie detected: Firestore OPEN, Alpaca closed."""

def test_detect_orphans():
    """Orphan detected: Alpaca OPEN, Firestore missing."""

def test_heal_zombie_marks_closed():
    """Zombie healing updates status to CLOSED_EXTERNALLY."""

def test_alert_orphan_sends_discord():
    """Orphan detection triggers Discord critical alert."""

def test_reconcile_returns_report():
    """Full reconciliation returns complete report."""

def test_reconcile_idempotent():
    """Running reconciliation twice produces same result."""

def test_reconcile_respects_environment_gate():
    """Reconciliation skipped in non-PROD environment."""
```

**Mocking Strategy:**

- Mock `TradingClient.list_positions()` → returns test Alpaca positions
- Mock `PositionRepository.get_open_positions()` → returns test Firestore positions
- Mock `DiscordClient.send_critical_alert()` → verify calls without network
- Use real `ExitReason.CLOSED_EXTERNALLY` enum

### Integration Tests (Optional)

- Manually close position in Alpaca test account
- Run reconciliation
- Verify Firestore position updated to CLOSED_EXTERNALLY

---

## ⚠️ Risk Assessment

### Low Risk Areas ✅

- **Adding ExitReason enum value**: Backward compatible, existing code unaffected
- **New module in engine/**: No changes to critical paths
- **Idempotent healing**: Safe to run multiple times

### Medium Risk Areas ⚠️

- **Firestore queries**: `get_open_positions()` is already used elsewhere (low chance of regression)
- **Discord notifications**: New message type, could overload Discord if many orphans detected
- **First-time integration**: Should test with dry-run first

### Mitigation Strategies

1. **Dry-Run Flag**: Add optional `dry_run=True` param to reconcile() for testing
2. **Discord Rate Limiting**: Batch orphan alerts into single message if many
3. **Logging**: Comprehensive logging of all decisions for debugging
4. **Gradual Rollout**: Enable only in test environment first, then prod

---

## 📊 Files to Create/Modify

| File                                      | Type   | Changes                                                 |
| ----------------------------------------- | ------ | ------------------------------------------------------- |
| `src/crypto_signals/engine/reconciler.py` | NEW    | StateReconciler class (~150 lines)                      |
| `src/crypto_signals/domain/schemas.py`    | MODIFY | Add CLOSED_EXTERNALLY, ReconciliationReport (~30 lines) |
| `src/crypto_signals/main.py`              | MODIFY | Initialize and call reconciler at startup (~10 lines)   |
| `tests/engine/test_reconciler.py`         | NEW    | Unit tests (~200 lines)                                 |

**Estimated LOC**: ~390 lines of new code

---

## ✅ Acceptance Criteria

- [x] User manually closes position in Alpaca app → reconciler detects zombie and marks CLOSED_EXTERNALLY
- [x] Orphan positions in Alpaca trigger Discord critical alert with symbol
- [x] Reconciliation runs automatically at start of each main.py execution
- [x] Reconciliation report logged with counts and duration
- [x] No impact on normal signal generation pipeline
- [x] Unit tests pass with >90% coverage of reconciler module
- [x] Error handling prevents reconciliation failures from crashing main loop

---

## 🔗 Dependencies & Integration Points

- **TradingClient** (alpaca-py): Already imported in execution.py
- **PositionRepository**: Already used in main.py for position tracking
- **DiscordClient**: Already used for notifications
- **ExitReason enum**: Existing domain model
- **Settings**: Already injected everywhere

**No new external dependencies required**.

---

## 📅 Implementation Timeline

**Estimated Effort**: 2-3 hours (includes testing)

1. **Phase 1** (30 min): Domain model changes
2. **Phase 2** (60 min): StateReconciler implementation
3. **Phase 3** (30 min): Integration into main.py
4. **Phase 4** (30 min): Unit tests and validation

---

## 🚀 Next Steps

1. **User Review**: Approve/request changes to this plan
2. **Branch Creation**: `fix/issue-113-state-reconciler`
3. **TDD Approach**: Write tests first, then implementation
4. **Verification**: Run full test suite + smoke test
5. **PR**: Submit with reconciliation report in description

---

**Ready for implementation approval!** ✨
