# Engineering Knowledge Base
*Central repository of lessons learned, API quirks, and architectural gotchas.*

## General
- [2024-03-20] **Workflow**: Always run `/verify` before PR to catch regression.

## APIs & Integrations
### Alpaca
- [2024-XX-XX] **Orders**: Market orders during extended hours are rejected. Use Limit orders.

### Firestore
- [2024-XX-XX] **Queries**: Composite queries require an index. Check logs for the creation link.

### GCP
- [2024-XX-XX] **Cloud Run**: Cold starts can exceed 10s. JIT warmup is essential.
