# Crypto Sentinel

**Automated cryptocurrency and equity trading signal generator with cloud-native architecture.**

## Overview

Crypto Sentinel is a production-ready trading bot that:
- 📊 Ingests market data for stocks and cryptocurrencies via Alpaca API
- 🔍 Analyzes technical indicators and patterns using confluence logic
- 🚀 Generates trading signals with risk management parameters
- 💬 Sends real-time Discord notifications
- ☁️ Stores signals in Google Cloud Firestore for persistence
- 📈 Archives trade history to BigQuery for analytics

## Features

### Core Capabilities
- **Multi-Asset Support**: Trades both cryptocurrencies (BTC, ETH, XRP) and equities (NVDA, QQQ, GLD)
- **Pattern Recognition**: Detects bullish hammer and bullish engulfing patterns
- **Technical Indicators**: RSI, MACD, Bollinger Bands, EMA, and more
- **Risk Management**: Automatic stop-loss calculation and position sizing
- **Cloud-Native**: Designed for containerized deployment on GCP

### Production Features
- ✅ **Secret Management**: Google Secret Manager integration
- ✅ **Rate Limiting**: Automatic throttling to respect API limits (200 req/min)
- ✅ **Retry Logic**: Exponential backoff for transient failures
- ✅ **Graceful Shutdown**: SIGTERM/SIGINT handling for clean container stops
- ✅ **Data Cleanup**: Automatic TTL via Firestore (30-day retention, no manual cleanup needed)
- ✅ **Structured Logging**: Context-rich logs with timing metrics
- ✅ **Health Checks**: Comprehensive service connectivity verification
- ✅ **Docker Support**: Multi-stage builds with security best practices

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Crypto Sentinel                          │
│                                                                 │
│  ┌──────────────┐    ┌─────────────┐    ┌──────────────┐     │
│  │   main.py    │───▶│  SignalGen  │───▶│   Discord    │     │
│  │ (Orchestrator)│    │   Engine    │    │ Notifications│     │
│  └──────────────┘    └─────────────┘    └──────────────┘     │
│         │                    │                                 │
│         ▼                    ▼                                 │
│  ┌──────────────┐    ┌─────────────┐                         │
│  │  MarketData  │    │  Patterns & │                         │
│  │   Provider   │    │ Indicators  │                         │
│  └──────────────┘    └─────────────┘                         │
│         │                    │                                 │
│         ▼                    ▼                                 │
│  ┌──────────────────────────────────┐                        │
│  │      Firestore (Signals)         │                        │
│  └──────────────────────────────────┘                        │
└─────────────────────────────────────────────────────────────────┘

External Services:
- Alpaca API (Market Data & Trading)
- Google Cloud Firestore (Signal Storage)
- Google Cloud BigQuery (Trade Analytics)
- Discord Webhooks (Notifications)
- Google Secret Manager (Credentials)
```

## Project Structure

```
crypto-signals/
├── src/crypto_signals/
│   ├── main.py                    # Application entrypoint
│   ├── config.py                  # Configuration management
│   ├── secrets_manager.py         # Secret Manager integration
│   ├── observability.py           # Structured logging & metrics
│   ├── engine/
│   │   └── signal_generator.py    # Signal generation orchestration
│   ├── market/
│   │   ├── data_provider.py       # Alpaca API wrapper
│   │   └── exceptions.py          # Custom exceptions
│   ├── analysis/
│   │   ├── indicators.py          # Technical indicators (RSI, MACD, etc.)
│   │   └── patterns.py            # Pattern detection logic
│   ├── notifications/
│   │   └── discord.py             # Discord webhook client
│   ├── repository/
│   │   └── firestore.py           # Firestore persistence layer
│   ├── pipelines/
│   │   ├── base.py                # BigQuery pipeline base
│   │   ├── trade_archival.py      # Trade archival pipeline
│   │   └── account_snapshot.py    # Account snapshot pipeline
│   ├── domain/
│   │   └── schemas.py             # Pydantic data models
│   └── scripts/
│       ├── health_check.py        # Service connectivity verification
│       └── cleanup_firestore.py   # Manual cleanup job (optional with automatic TTL)
├── tests/                         # Comprehensive test suite
├── Dockerfile                     # Multi-stage production build
├── docker-compose.yml             # Local development setup
├── DEPLOYMENT.md                  # Cloud deployment guide
├── pyproject.toml                 # Poetry dependencies
└── README.md                      # This file
```

## Quick Start

### Prerequisites

- Python 3.9+
- Poetry (dependency management)
- Docker (optional, for containerized deployment)
- Google Cloud Project (for production deployment)
- Alpaca API credentials
- Discord webhook URL

### Local Development Setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/lagarcess/crypto-signals.git
   cd crypto-signals
   ```

2. **Install dependencies**:
   ```bash
   poetry install
   ```

3. **Configure environment**:
   Create a `.env` file in the project root:
   ```env
   # Alpaca API
   ALPACA_API_KEY=your_api_key
   ALPACA_SECRET_KEY=your_secret_key
   ALPACA_PAPER_TRADING=true

   # Google Cloud
   GOOGLE_CLOUD_PROJECT=your-gcp-project-id
   GOOGLE_APPLICATION_CREDENTIALS=./path/to/service-account.json

   # Discord
   DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your-webhook-url
   MOCK_DISCORD=false  # Set to true for testing without sending

   # Optional
   RATE_LIMIT_DELAY=0.5  # Seconds between API requests
   ```

4. **Run health check**:
   ```bash
   poetry run python -m crypto_signals.scripts.health_check
   ```

5. **Run the bot**:
   ```bash
   poetry run python -m crypto_signals.main
   ```

### Docker Setup

1. **Build the image**:
   ```bash
   docker build -t crypto-signals:latest .
   ```

2. **Run with Docker Compose**:
   ```bash
   # Create secrets directory and add GCP key
   mkdir -p secrets
   cp /path/to/service-account.json secrets/gcp-key.json

   # Start the service
   docker-compose up
   ```

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ALPACA_API_KEY` | Yes | - | Alpaca API key |
| `ALPACA_SECRET_KEY` | Yes | - | Alpaca secret key |
| `ALPACA_PAPER_TRADING` | No | `true` | Use paper trading account |
| `GOOGLE_CLOUD_PROJECT` | Yes | - | GCP project ID |
| `GOOGLE_APPLICATION_CREDENTIALS` | No* | - | Path to service account JSON (*auto in cloud) |
| `DISCORD_WEBHOOK_URL` | Yes | - | Discord webhook URL |
| `MOCK_DISCORD` | No | `false` | Mock Discord notifications |
| `RATE_LIMIT_DELAY` | No | `0.5` | Delay between API requests (seconds) |
| `DISABLE_SECRET_MANAGER` | No | `false` | Disable Secret Manager (local dev) |

### Portfolio Configuration

Edit `config.py` to customize the symbols to analyze:

```python
CRYPTO_SYMBOLS: List[str] = [
    "BTC/USD",
    "ETH/USD",
    "XRP/USD",
]

EQUITY_SYMBOLS: List[str] = [
    "NVDA",
    "QQQ",
    "GLD",
]
```

## Deployment

See [DEPLOYMENT.md](DEPLOYMENT.md) for comprehensive cloud deployment instructions, including:
- Google Secret Manager setup
- Cloud Run deployment
- Cloud Scheduler configuration
- Monitoring and alerting
- Cost optimization strategies

## Development

### Running Tests

```bash
# Run all tests
poetry run pytest

# Run with coverage
poetry run pytest --cov=crypto_signals

# Run specific test file
poetry run pytest tests/test_main.py
```

### Code Quality

```bash
# Format code
poetry run black src/ tests/

# Lint code
poetry run flake8 src/ tests/

# Type checking
poetry run mypy src/
```

### Pre-commit Hooks

```bash
# Install pre-commit hooks
poetry run pre-commit install

# Run manually
poetry run pre-commit run --all-files
```

## Security Considerations

1. **Never commit secrets**: Use `.env` locally and Secret Manager in production
2. **Non-root container**: Dockerfile runs as user `appuser` (UID 1000)
3. **Minimal base image**: Uses `python:3.11-slim` for reduced attack surface
4. **Secret rotation**: Rotate API keys and webhooks regularly
5. **IAM least privilege**: Grant only necessary permissions to service accounts

## Monitoring & Observability

### Structured Logging

All operations include contextual information:
```
2024-01-15 10:30:45 - crypto_signals.main - INFO - Analyzing BTC/USD | symbol=BTC/USD | asset_class=CRYPTO
2024-01-15 10:30:47 - crypto_signals.main - INFO - Completed: signal_generation | duration=2.34s | symbol=BTC/USD
```

### Metrics Collection

Built-in metrics tracking:
- Success/failure rates per operation
- Execution duration (min/avg/max)
- Total operations count
- Error rates and types

### Health Checks

Run health checks to verify connectivity:
```bash
poetry run python -m crypto_signals.scripts.health_check
```

Verifies:
- ✅ Alpaca Trading API
- ✅ Alpaca Market Data API
- ✅ Google Cloud Firestore
- ✅ Google Cloud BigQuery
- ✅ Discord Webhook

## Troubleshooting

### Rate Limit Errors

Increase `RATE_LIMIT_DELAY`:
```env
RATE_LIMIT_DELAY=1.0  # Increase from default 0.5s
```

### Memory Issues

Reduce portfolio size or increase container memory:
```bash
docker-compose up --scale crypto-signals=1 --memory=2g
```

### Secret Loading Failures

Check Secret Manager permissions:
```bash
gcloud projects get-iam-policy $GOOGLE_CLOUD_PROJECT
```

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/amazing-feature`
3. Commit your changes: `git commit -m 'Add amazing feature'`
4. Push to the branch: `git push origin feature/amazing-feature`
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the LICENSE file for details.

## Acknowledgments

- [Alpaca Markets](https://alpaca.markets/) for market data and trading API
- [pandas-ta](https://github.com/twopirllc/pandas-ta) for technical indicators
- Google Cloud Platform for infrastructure services

## Support

For issues, questions, or contributions, please open an issue on GitHub.

---

**⚠️ Disclaimer**: This software is for educational purposes only. Cryptocurrency and stock trading involves substantial risk of loss. Use at your own risk.
