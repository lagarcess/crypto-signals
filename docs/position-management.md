# Position Management & TP Automation

Automatic position sizing and stop-loss management when take-profit targets are hit.

## Scaling Strategy

| Stage | Scale Out | Remaining | Stop Moves To |
|-------|-----------|-----------|---------------|
| **Entry** | - | 100% | Initial SL |
| **TP1 Hit** | 50% | 50% | Breakeven (entry) |
| **TP2 Hit** | 50% of remaining | 25% | TP1 level |
| **TP3 Hit** | Runner exits | 0% | TP2 level (trailed) |

## How It Works

When `ENABLE_EXECUTION=True`, the system automatically manages positions:

### Take-Profit Stages

1. **TP1 Detected** → Sells 50%, moves stop to breakeven
2. **TP2 Detected** → Sells 50% of remaining (25% total), moves stop to TP1
3. **TP3 Detected** → Closes runner position completely

### Active Trailing (Chandelier Exit)

When price moves favorably during Runner phase:
- Chandelier Exit is recalculated each day
- If new stop > current stop → Alpaca order is modified
- Discord notified if movement > 1%

### Exit Triggers

| Trigger | Alpaca Action |
|---------|---------------|
| **TP3 Hit** | Close remaining position |
| **Invalidation** | Emergency close |
| **Expiration** | Auto-cancel (no action) |

## Schema Tracking Fields

| Field | Description |
|-------|-------------|
| `original_qty` | Quantity before any scale-outs |
| `scaled_out_qty` | Cumulative quantity sold |
| `scaled_out_price` | Fill price of the most recent scale-out |
| `scaled_out_at` | Timestamp of the most recent scale-out |
| `breakeven_applied` | Whether stop moved to breakeven |

## Discord Notifications

Each TP level sends an update with action hints:

- **TP1**: "ℹ️ Scaling Out (50%) & Stop -> Breakeven"
- **TP2**: "ℹ️ Scaling Out (50% remaining) & Stop -> TP1"
- **TP3**: "🏃 Runner Complete - Trailing stop hit"

## Configuration

```env
# Required for automated execution
ENABLE_EXECUTION=true
ALPACA_PAPER_TRADING=true  # Safety guard

# Position sizing
RISK_PER_TRADE=100.0  # Fixed dollar risk per trade
```

## Data Life Cycle (Self-Cleaning)

To maintain database hygiene and manage storage costs, positions have a fixed **90-day physical lifecycle**:
- **Mechanism**: The `delete_at` field is automatically set to `now + 90 days` upon position creation.
- **TTL Enforcement**: Google Cloud Firestore automatically prunes expired positions via the `delete_at` TTL policy.
- **Manual Cleanup**: The `cleanup_firestore.py` script can be used to manually trigger pruning across all operational collections.

## Related Files

- [`execution.py`](../src/crypto_signals/engine/execution.py) - `scale_out_position()`, `move_stop_to_breakeven()`
- [`main.py`](../src/crypto_signals/main.py) - TP automation logic
- [`schemas.py`](../src/crypto_signals/domain/schemas.py) - Position tracking fields
