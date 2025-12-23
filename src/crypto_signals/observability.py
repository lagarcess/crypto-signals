"""
Structured Logging Utilities.

This module provides structured logging capabilities for better observability
in cloud environments. It adds contextual information and timing metrics
to all log messages.
"""

import time
from contextlib import contextmanager
from functools import wraps
from typing import Any, Dict, Optional

from loguru import logger

# Remove default handler and add a new one that directs to stdout/stderr as appropriate
# Note: In a library or shared module, we might want to avoid configuring sink globally,
# but this looks like an application module.
# For now, we will rely on default loguru configuration or let main.py configure it.
# However, to ensure `logger` is available and works as expected, we import it.


class StructuredLogger:
    """Wrapper for adding structured context to Python logging."""

    def __init__(self, name: str, context: Optional[Dict[str, Any]] = None):
        """
        Initialize structured logger.

        Args:
            name: Logger name (typically __name__) - Ignored by loguru generally,
                  but kept for compatibility.
            context: Default context to include in all log messages
        """
        self.context = context or {}
        # Bind the initial context
        self.logger = logger.bind(**self.context)

    def _format_message(
        self, msg: str, extra_context: Optional[Dict[str, Any]] = None
    ) -> str:
        """Format message with context."""
        # Loguru handles structure via .bind(), but to preserve the existing
        # "msg | k=v" text format in the message itself (which the user might rely on),
        # we can still do this formatting.
        # Alternatively, we could trust loguru's sink formatting, but that changes output.
        # We will maintain existing behavior of modifying the message string.
        context = {**self.context, **(extra_context or {})}
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"{msg} | {context_str}"
        return msg

    def debug(self, msg: str, **context):
        """Log debug message with context."""
        # We use the bound logger, but also format the message to keep compat
        self.logger.debug(self._format_message(msg, context))

    def info(self, msg: str, **context):
        """Log info message with context."""
        self.logger.info(self._format_message(msg, context))

    def warning(self, msg: str, **context):
        """Log warning message with context."""
        self.logger.warning(self._format_message(msg, context))

    def error(self, msg: str, exc_info=False, **context):
        """Log error message with context."""
        # Loguru handles exceptions with opt(exception=True) or just passing exception object
        # but exc_info=True is standard logging. Loguru supports it via .opt(exception=...)
        if exc_info:
            self.logger.opt(exception=True).error(self._format_message(msg, context))
        else:
            self.logger.error(self._format_message(msg, context))

    def critical(self, msg: str, exc_info=False, **context):
        """Log critical message with context."""
        if exc_info:
            self.logger.opt(exception=True).critical(self._format_message(msg, context))
        else:
            self.logger.critical(self._format_message(msg, context))

    def add_context(self, **context):
        """Add persistent context to this logger."""
        self.context.update(context)
        # Re-bind logger with new context
        self.logger = logger.bind(**self.context)

    def remove_context(self, *keys):
        """Remove keys from persistent context."""
        for key in keys:
            self.context.pop(key, None)
        self.logger = logger.bind(**self.context)


@contextmanager
def log_execution_time(logger_instance: Any, operation: str, **context):
    """
    Context manager to log execution time of an operation.

    Args:
        logger_instance: Logger instance (StructuredLogger, loguru logger, or std logger)
        operation: Name of the operation being timed
        **context: Additional context to include in log messages
    """
    context_str = " | ".join(f"{k}={v}" for k, v in context.items()) if context else ""
    full_context = f" | {context_str}" if context_str else ""

    start_time = time.time()
    # Support both our StructuredLogger and raw loguru/logging loggers
    # StructuredLogger has .info(), loguru has .info()
    logger_instance.info(f"Starting: {operation}{full_context}")

    try:
        yield
    except Exception as e:
        elapsed = time.time() - start_time
        msg = f"Failed: {operation} | duration={elapsed:.2f}s{full_context} | error={str(e)}"

        if hasattr(logger_instance, "opt"):  # Loguru
            logger_instance.opt(exception=True).error(msg)
        elif hasattr(logger_instance, "error"):
            # Check if it accepts exc_info (std logging or StructuredLogger)
            # StructuredLogger.error signature: (msg, exc_info=False, **context)
            try:
                logger_instance.error(msg, exc_info=True)
            except TypeError:
                # Fallback if logger doesn't support exc_info arg (unlikely for std/wrapper)
                logger_instance.error(msg)
        else:
            print(f"ERROR: {msg}")  # Fallback

        raise
    else:
        elapsed = time.time() - start_time
        logger_instance.info(
            f"Completed: {operation} | duration={elapsed:.2f}s{full_context}"
        )


def timed(operation_name: Optional[str] = None):
    """
    Decorator to automatically log execution time of a function.
    """

    def decorator(func):
        op_name = operation_name or func.__name__

        @wraps(func)
        def wrapper(*args, **kwargs):
            # Use loguru logger directly
            start_time = time.time()

            try:
                logger.info(f"Starting: {op_name}")
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"Completed: {op_name} | duration={elapsed:.2f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.opt(exception=True).error(
                    f"Failed: {op_name} | duration={elapsed:.2f}s | error={str(e)}"
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

    def log_summary(self, logger_instance: Any):
        """Log metrics summary."""
        summary = self.get_summary()
        if not summary:
            logger_instance.info("No metrics recorded")
            return

        logger_instance.info("=== METRICS SUMMARY ===")
        for operation, stats in summary.items():
            logger_instance.info(
                f"{operation}: {stats['total_operations']} ops, "
                f"{stats['success_rate']:.1f}% success, "
                f"avg {stats['avg_duration_seconds']}s"
            )


# Global metrics collector instance
_global_metrics = MetricsCollector()


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    return _global_metrics
