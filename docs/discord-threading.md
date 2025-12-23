# Discord Threaded Signal Lifecycle

All signal lifecycle updates (TP hits, invalidations, expirations) are pinned to a single Discord thread.

## Architecture

![Signal Lifecycle Architecture](./images/signal-lifecycle-architecture.png)

## How It Works

### Thread Creation

1. `discord.send_signal()` is called with `?wait=true` to get the message ID
2. The message ID serves as the `thread_id` for Forum channels
3. This `thread_id` is saved to `signal.discord_thread_id`
4. The signal (with thread_id) is persisted to Firestore

### Lifecycle Updates

1. Signal is fetched from Firestore (includes `discord_thread_id`)
2. `discord.send_message()` is called with `thread_id=signal.discord_thread_id`
3. Discord routes the message to the existing thread using `?thread_id=`

### Self-Healing

If a signal lacks a `discord_thread_id` (due to initial notification failure):
1. System detects the missing thread_id during validation
2. A new thread is created via `discord.send_signal()`
3. The new thread_id is persisted for future updates

## Schema Fields

| Model | Field | Description |
|-------|-------|-------------|
| `Signal` | `discord_thread_id` | Links lifecycle updates to original broadcast |
| `Position` | `discord_thread_id` | Inherited from Signal on fill |
| `TradeExecution` | `discord_thread_id` | Propagated during archival for analytics |

## Webhook Routing

Messages are routed based on `TEST_MODE` and asset class:

| Scenario | Mode | Asset Class | Target Webhook |
| --- | --- | --- | --- |
| **Development/Tests** | `TEST_MODE=true` | Any | `TEST_DISCORD_WEBHOOK` |
| **Live Production** | `TEST_MODE=false` | `CRYPTO` | `LIVE_CRYPTO_DISCORD_WEBHOOK_URL` |
| **Live Production** | `TEST_MODE=false` | `EQUITY` | `LIVE_STOCK_DISCORD_WEBHOOK_URL` |
| **System Messages** | Any | None | `TEST_DISCORD_WEBHOOK` |

## Visual Testing

```powershell
# Ensure TEST_DISCORD_WEBHOOK is set in .env

# Test mode (default) - all messages go to test webhook
poetry run python scripts/visual_discord_test.py success      # Signal → TP1 → TP2 → TP3
poetry run python scripts/visual_discord_test.py invalidation # Signal → Invalidation
poetry run python scripts/visual_discord_test.py expiration   # Signal → Expiration
poetry run python scripts/visual_discord_test.py trail        # Runner trail path
poetry run python scripts/visual_discord_test.py all          # All paths

# Live mode - routes by asset class
poetry run python scripts/visual_discord_test.py all --mode live
```

| Path | Messages | Flow |
|------|----------|------|
| **Success** | 4 | Initial → TP1 → TP2 → TP3 |
| **Invalidation** | 2 | Initial → Invalidation |
| **Expiration** | 2 | Initial → Expiration |
| **Trail** | 5 | Initial → TP1 → Trail Updates → TP3 |
