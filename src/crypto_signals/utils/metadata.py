import os
import subprocess
from typing import Any, Dict

from crypto_signals.config import Settings
from loguru import logger


def get_git_hash() -> str:
    """
    Get the short git hash of the current revision.
    Returns 'unknown' if git command fails.
    """
    try:
        # Run git rev-parse --short HEAD
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            timeout=2,
        )
        return result.stdout.strip()
    except Exception as e:
        logger.warning(f"Failed to get git hash from command: {e}")
        # Fallback to Environment Variables (Common in Docker/CI)
        if git_sha := os.getenv("GIT_SHA"):
            return git_sha
        if revision_id := os.getenv("REVISION_ID"):
            return revision_id
        return "unknown"


def get_job_context(settings: Settings) -> Dict[str, Any]:
    """
    Extract critical configuration settings for job metadata.
    """
    critical_settings = {
        "ENVIRONMENT",
        "TEST_MODE",
        "MAX_CRYPTO_POSITIONS",
        "MAX_EQUITY_POSITIONS",
        "RISK_PER_TRADE",
        "ENABLE_EXECUTION",
        "ALPACA_PAPER_TRADING",
    }
    return settings.model_dump(include=critical_settings)
