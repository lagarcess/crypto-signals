"""
Structured Logging Utilities.

This module provides structured logging capabilities for better observability
in cloud environments. It adds contextual information and timing metrics
to all log messages.
"""

import logging
import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict, Optional


class StructuredLogger:
    """Wrapper for adding structured context to Python logging."""

    def __init__(self, name: str, context: Optional[Dict[str, Any]] = None):
        """
        Initialize structured logger.

        Args:
            name: Logger name (typically __name__)
            context: Default context to include in all log messages
        """
        self.logger = logging.getLogger(name)
        self.context = context or {}

    def _format_message(self, msg: str, extra_context: Optional[Dict[str, Any]] = None) -> str:
        """Format message with context."""
        context = {**self.context, **(extra_context or {})}
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"{msg} | {context_str}"
        return msg

    def debug(self, msg: str, **context):
        """Log debug message with context."""
        self.logger.debug(self._format_message(msg, context))

    def info(self, msg: str, **context):
        """Log info message with context."""
        self.logger.info(self._format_message(msg, context))

    def warning(self, msg: str, **context):
        """Log warning message with context."""
        self.logger.warning(self._format_message(msg, context))

    def error(self, msg: str, exc_info=False, **context):
        """Log error message with context."""
        self.logger.error(self._format_message(msg, context), exc_info=exc_info)

    def critical(self, msg: str, exc_info=False, **context):
        """Log critical message with context."""
        self.logger.critical(self._format_message(msg, context), exc_info=exc_info)

    def add_context(self, **context):
        """Add persistent context to this logger."""
        self.context.update(context)

    def remove_context(self, *keys):
        """Remove keys from persistent context."""
        for key in keys:
            self.context.pop(key, None)


@contextmanager
def log_execution_time(logger: logging.Logger, operation: str, **context):
    """
    Context manager to log execution time of an operation.

    Args:
        logger: Logger instance
        operation: Name of the operation being timed
        **context: Additional context to include in log messages

    Example:
        with log_execution_time(logger, "fetch_market_data", symbol="BTC/USD"):
            data = fetch_data()
    """
    context_str = " | ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    full_context = f" | {context_str}" if context_str else ""

    start_time = time.time()
    logger.info(f"Starting: {operation}{full_context}")

    try:
        yield
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(
            f"Failed: {operation} | duration={elapsed:.2f}s{full_context} | error={str(e)}",
            exc_info=True,
        )
        raise
    else:
        elapsed = time.time() - start_time
        logger.info(f"Completed: {operation} | duration={elapsed:.2f}s{full_context}")


def timed(operation_name: Optional[str] = None):
    """
    Decorator to automatically log execution time of a function.

    Args:
        operation_name: Optional name for the operation (defaults to function name)

    Example:
        @timed("fetch_data")
        def fetch_market_data(symbol):
            ...
    """

    def decorator(func):
        op_name = operation_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            logger = logging.getLogger(func.__module__)
            start_time = time.time()

            try:
                logger.info(f"Starting: {op_name}")
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"Completed: {op_name} | duration={elapsed:.2f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(
                    f"Failed: {op_name} | duration={elapsed:.2f}s | error={str(e)}",
                    exc_info=True,
                )
                raise

        return wrapper

    return decorator


class MetricsCollector:
    """
    Simple metrics collector for tracking operation statistics.

    This provides basic metrics tracking. For production, consider using
    Prometheus client library or Cloud Monitoring.
    """

    def __init__(self):
        """Initialize metrics collector."""
        self.metrics: Dict[str, Dict[str, Any]] = {}

    def record_success(self, operation: str, duration: float):
        """Record successful operation."""
        if operation not in self.metrics:
            self.metrics[operation] = {
                "success_count": 0,
                "failure_count": 0,
                "total_duration": 0.0,
                "min_duration": float("inf"),
                "max_duration": 0.0,
            }

        m = self.metrics[operation]
        m["success_count"] += 1
        m["total_duration"] += duration
        m["min_duration"] = min(m["min_duration"], duration)
        m["max_duration"] = max(m["max_duration"], duration)

    def record_failure(self, operation: str, duration: float):
        """Record failed operation."""
        if operation not in self.metrics:
            self.metrics[operation] = {
                "success_count": 0,
                "failure_count": 0,
                "total_duration": 0.0,
                "min_duration": float("inf"),
                "max_duration": 0.0,
            }

        m = self.metrics[operation]
        m["failure_count"] += 1
        m["total_duration"] += duration

    def get_summary(self) -> Dict[str, Dict[str, Any]]:
        """Get metrics summary."""
        summary = {}
        for operation, m in self.metrics.items():
            total_ops = m["success_count"] + m["failure_count"]
            avg_duration = m["total_duration"] / total_ops if total_ops > 0 else 0.0

            summary[operation] = {
                "total_operations": total_ops,
                "success_count": m["success_count"],
                "failure_count": m["failure_count"],
                "success_rate": (
                    m["success_count"] / total_ops * 100 if total_ops > 0 else 0.0
                ),
                "avg_duration_seconds": round(avg_duration, 2),
                "min_duration_seconds": (
                    round(m["min_duration"], 2)
                    if m["min_duration"] != float("inf")
                    else None
                ),
                "max_duration_seconds": round(m["max_duration"], 2),
            }

        return summary

    def log_summary(self, logger: logging.Logger):
        """Log metrics summary."""
        summary = self.get_summary()
        if not summary:
            logger.info("No metrics recorded")
            return

        logger.info("=== METRICS SUMMARY ===")
        for operation, stats in summary.items():
            logger.info(
                f"{operation}: {stats['total_operations']} ops, "
                f"{stats['success_rate']:.1f}% success, "
                f"avg {stats['avg_duration_seconds']}s"
            )


# Global metrics collector instance
_global_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    return _global_metrics
