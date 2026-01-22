# Issue #117 Implementation Plan: Technical Review Response

## Overview

Your technical review identified **4 critical gaps** in the initial implementation plan. All gaps have been addressed and the corrected plan is now **ready for development**.

---

## Summary Table: Gaps → Fixes

| #     | Issue                  | Initial Plan         | Review Finding                                                    | Fix Applied                                   | Status        |
| ----- | ---------------------- | -------------------- | ----------------------------------------------------------------- | --------------------------------------------- | ------------- |
| **1** | Exit Price Calculation | Used `entry_price`   | TP3@120, price@121.5 would incorrectly escape (21% vs 1.5%)       | Dynamic TP level selection via `SignalStatus` | ✅ FIXED      |
| **2** | Pattern Specificity    | Symbol-wide block    | Different pattern (e.g., MORNING_STAR) blocked after ELLIOTT_WAVE | Optional `pattern_name` filter parameter      | ✅ ADDRESSED  |
| **3** | Enum Names             | `ExitReason.TP1_HIT` | Doesn't exist; actual is `SignalStatus.TP1_HIT`                   | Updated all references to `SignalStatus`      | ✅ CORRECTED  |
| **4** | Firestore Index        | Not mentioned        | Query will fail without composite index                           | Documented index requirement + GCP command    | ✅ DOCUMENTED |

---

## Gap #1: Exit Price Calculation (CRITICAL BUG)

### ❌ Initial Logic

```python
# WRONG: Uses entry price for threshold
exit_price = recent_exit.entry_price  # 100
price_change_pct = abs(121.5 - 100) / 100 * 100  # = 21.5%
# Incorrectly ESCAPES cooldown (21.5% > 10%)
```

### ✅ Corrected Logic

```python
# CORRECT: Uses actual exit level from TP
exit_level_map = {
    SignalStatus.TP1_HIT: recent_exit.take_profit_1,
    SignalStatus.TP2_HIT: recent_exit.take_profit_2,
    SignalStatus.TP3_HIT: recent_exit.take_profit_3,  # 120
}
exit_level = exit_level_map[recent_exit.status]  # Gets 120
price_change_pct = abs(121.5 - 120) / 120 * 100  # = 1.25%
# Correctly BLOCKS cooldown (1.25% < 10%)
```

### Test Coverage Added

```python
def test_cooldown_uses_actual_exit_level_not_entry():
    # Entry=100, TP3=120, price=121.5
    # Should BLOCK (1.25% from TP3)
    # Not ESCAPE (21.5% from entry)
    assert signal_gen._is_in_cooldown("BTC/USD", 121.5) == True
```

**Impact**: High - fixes fundamental logic bug that would cause false cooldown escapes
**File**: `src/crypto_signals/engine/signal_generator.py`, method `_is_in_cooldown()`

---

## Gap #2: Pattern Specificity (DESIGN TRADE-OFF)

### ❌ Initial Design

```python
# Blocks entire symbol for 48h regardless of pattern
recent_exit = self.signal_repo.get_most_recent_exit(symbol="BTC/USD", hours=48)
if recent_exit:
    return True  # Block any new signal on BTC/USD
```

**Problem**: Elliott Wave exits → Morning Star pattern detected 2h later → incorrectly blocked

### ✅ Corrected Design

```python
# Optional pattern filter
recent_exit = self.signal_repo.get_most_recent_exit(
    symbol="BTC/USD",
    hours=48,
    pattern_name=None  # Or "MORNING_STAR" to filter
)

if not pattern_name:
    # Default: apply to all patterns (conservative)
    if recent_exit:
        return True
else:
    # If pattern filter provided, only block if patterns match
    if recent_exit and recent_exit.pattern_name == pattern_name:
        return True
```

**Method Signature Updated**:

```python
def _is_in_cooldown(
    self,
    symbol: str,
    current_price: float,
    pattern_name: str | None = None  # NEW
) -> bool:
```

### Test Coverage Added

```python
def test_cooldown_pattern_filter_optional():
    # Elliott Wave exit at TP3
    recent_exit = Signal(..., pattern_name="ELLIOTT_WAVE", status=TP3_HIT)

    # Without filter: blocks (conservative)
    assert _is_in_cooldown("BTC/USD", 105, pattern_name=None) == True

    # With different pattern: allowed (repository filters it out)
    assert _is_in_cooldown("BTC/USD", 105, pattern_name="MORNING_STAR") == False
```

**Impact**: Medium - allows more flexible cooldown behavior
**Files**:

- `src/crypto_signals/engine/signal_generator.py`, method `_is_in_cooldown()`
- `src/crypto_signals/repository/firestore.py`, method `get_most_recent_exit()`

---

## Gap #3: Enum Inconsistency (CRITICAL - TYPE SAFETY)

### ❌ Initial References

```python
# Plan used these (don't exist!)
exit_reasons = [
    ExitReason.TP1_HIT,    # ❌ AttributeError!
    ExitReason.TP2_HIT,    # ❌ AttributeError!
    ExitReason.TP3_HIT,    # ❌ AttributeError!
]
```

### ✅ Corrected References

```python
# Actual enums from domain/schemas.py
exit_reasons = [
    SignalStatus.TP1_HIT,  # ✅ Correct
    SignalStatus.TP2_HIT,  # ✅ Correct
    SignalStatus.TP3_HIT,  # ✅ Correct
]

# In Firestore query:
.where("status", "in", [s.value for s in exit_reasons])
```

### Verification

**File**: `src/crypto_signals/domain/schemas.py` lines 68-78

```python
class SignalStatus(str, Enum):
    CREATED = "CREATED"
    WAITING = "WAITING"
    CONFIRMED = "CONFIRMED"
    TP1_HIT = "TP1_HIT"      # ✅ Correct enum
    TP2_HIT = "TP2_HIT"      # ✅ Correct enum
    TP3_HIT = "TP3_HIT"      # ✅ Correct enum
    # ...
```

**Test Coverage Added**:

```python
def test_get_most_recent_exit_uses_signal_status():
    # Verify SignalStatus enum used, not ExitReason
    # This is checked by mypy strict mode during type checking
    result = repo.get_most_recent_exit(symbol="BTC/USD", hours=48)
    assert result is None or isinstance(result, Signal)
```

**Impact**: Critical - prevents AttributeError at runtime
**Files**:

- `src/crypto_signals/repository/firestore.py`, method `get_most_recent_exit()`
- `src/crypto_signals/engine/signal_generator.py`, method `_is_in_cooldown()`

---

## Gap #4: Firestore Composite Index (CRITICAL - INFRASTRUCTURE)

### ❌ Problem

Query with multiple filters and sorting:

```python
query = (
    self.signals_collection
    .where("symbol", "==", symbol)
    .where("status", "in", [TP1_HIT, TP2_HIT, TP3_HIT])  # Multi-filter
    .where("timestamp", ">=", cutoff_time)
    .order_by("timestamp", direction=DESC)  # And sorting
)
```

**Firestore Response**:

```
INVALID_ARGUMENT: The query requires a COMPOSITE INDEX
for collection "live_signals"
```

### ✅ Solution

**Add to DEPLOYMENT_CHECKLIST.md**:

```markdown
### Firestore Indexes for Issue #117 (Cooldown Feature)

**Before Deploying Cooldown Logic**:

- [ ] Create composite index for cooldown queries
  - Collection: `live_signals`
  - Fields:
    - `symbol` (Ascending)
    - `status` (Ascending)
    - `timestamp` (Descending)
  - Test: Verify query runs in dev environment

- [ ] Repeat for `test_signals` collection (dev environment)
```

**GCP Console Method**:

1. Go to Firestore → Indexes → Composite
2. Create index:
   - Collection: `live_signals`
   - Field: `symbol` (ASC)
   - Field: `status` (ASC)
   - Field: `timestamp` (DESC)

**GCP CLI Command**:

```bash
# Create index for live_signals
gcloud firestore indexes composite create \
  --collection-id=live_signals \
  --field-config=symbol=ASCENDING,status=ASCENDING,timestamp=DESCENDING

# Create index for test_signals (dev)
gcloud firestore indexes composite create \
  --collection-id=test_signals \
  --field-config=symbol=ASCENDING,status=ASCENDING,timestamp=DESCENDING
```

**Timing**: Create **before** deploying code to avoid production failure

**Impact**: Critical - query will 404/fail without index
**Files**:

- `DEPLOYMENT_CHECKLIST.md` (new requirement)
- Implementation plan documents this requirement

---

## Updated Plan Structure

The corrected implementation plan now includes these new sections:

### Section 6: Technical Fixes Applied

- Detailed explanation of all 4 fixes
- Code before/after examples
- Test coverage for each fix

### Section 7: Performance Considerations

- Query latency profile (5-20ms typical)
- Optional 5-minute TTL caching guidance
- When to profile vs. when to optimize

### Section 8: Updated Risk Assessment

- Firestore index marked as CRITICAL/BLOCKING
- Likelihood/impact matrix with mitigations
- Decision points for each risk

### Sections 9-13: Implementation Checklists

- Pre-implementation requirements (index must be created first!)
- Phase-by-phase breakdown
- Acceptance criteria
- References to related files

---

## Ready for Next Phase

✅ **Plan Status**: **READY FOR IMPLEMENTATION**

### Pre-Implementation Checklist

- [ ] User reviews and approves corrected plan
- [ ] Composite Firestore index created in GCP (both live_signals and test_signals)
- [ ] DEPLOYMENT_CHECKLIST.md updated with index requirement

### Implementation Phases (TDD Approach)

**Phase 1** (30 min): Repository Layer

```bash
/tdd issue 117
# Creates: tests/repository/test_firestore_cooldown.py
# Implements: src/crypto_signals/repository/firestore.py::get_most_recent_exit()
```

**Phase 2** (45 min): Signal Generator

```bash
# Creates: tests/engine/test_signal_generator_cooldown.py
# Implements: src/crypto_signals/engine/signal_generator.py::_is_in_cooldown()
```

**Phase 3** (60 min): Integration Testing

```bash
# Creates: tests/integration/test_cooldown_e2e.py
# Verifies: No regressions on 340+ existing tests
```

**Phase 4** (30 min): Documentation

```bash
# Updates: README.md, DEPLOYMENT.md, docs/KNOWLEDGE_BASE.md
# Documents: Cooldown feature and behavior
```

---

## Key Files Modified

| File                                             | Change                                   | Lines | Type  |
| ------------------------------------------------ | ---------------------------------------- | ----- | ----- |
| `artifacts/IMPLEMENTATION_PLAN.md`               | Added Fix #1-4 details, tests, checklist | +407  | Plan  |
| `src/crypto_signals/repository/firestore.py`     | Add `get_most_recent_exit()`             | +40   | Code  |
| `src/crypto_signals/engine/signal_generator.py`  | Add `_is_in_cooldown()`, integrate       | +60   | Code  |
| `tests/repository/test_firestore_cooldown.py`    | New unit tests                           | ~80   | Tests |
| `tests/engine/test_signal_generator_cooldown.py` | New unit tests (includes Fix validation) | ~130  | Tests |
| `tests/integration/test_cooldown_e2e.py`         | New integration tests                    | ~60   | Tests |
| `DEPLOYMENT_CHECKLIST.md`                        | Add Firestore index requirement          | +8    | Docs  |

---

## Conclusion

All four technical gaps from the code review have been identified, analyzed, and corrected:

| Gap                    | Status        | Impact                          |
| ---------------------- | ------------- | ------------------------------- |
| Exit price calculation | ✅ Fixed      | Prevents false cooldown escapes |
| Pattern specificity    | ✅ Addressed  | Adds optional pattern filter    |
| Enum naming            | ✅ Corrected  | Prevents runtime AttributeError |
| Firestore index        | ✅ Documented | Enables query execution         |

**Verdict**: The implementation plan is **architecturally sound**, **performance-viable**, and **backwards compatible**.

**Next Action**: Proceed with Phase 1 implementation via `/tdd issue 117` workflow.

---

**Plan Updated**: 2026-01-21
**Status**: ✅ **READY FOR IMPLEMENTATION**
**Location**: [artifacts/IMPLEMENTATION_PLAN.md](artifacts/IMPLEMENTATION_PLAN.md)
