#!/bin/bash
# setup.sh: Bootstrap the Crypto Sentinel development environment

echo "🔵 [Setup] Starting environment initialization..."

# 1. Check Python Version
python --version

# 2. Install Poetry (if not present)
if ! command -v poetry &> /dev/null; then
    echo "🔵 [Setup] Installing Poetry..."
    pip install poetry
else
    echo "🟢 [Setup] Poetry is already installed."
fi

# 3. Configure Poetry (Local virtualenv)
poetry config virtualenvs.in-project true

# 4. Install Dependencies
echo "🔵 [Setup] Installing dependencies via Poetry..."
poetry install

echo "🟢 [Setup] Environment validation complete. ready to trade."
