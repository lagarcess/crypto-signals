#!/usr/bin/env python
"""
Cloud Run Log Analyzer CLI.

Fetches and analyzes Google Cloud Run execution logs to identify critical
errors and specific events like 'Zombie' or 'Orphan' positions.
"""
import typer
from loguru import logger

app = typer.Typer()


@app.command()
def analyze(
    service: str = typer.Option(
        "crypto-signals-v2",
        "--service",
        "-s",
        help="The name of the Cloud Run service to analyze.",
    ),
    hours: int = typer.Option(
        24,
        "--hours",
        "-h",
        help="The number of hours of logs to retrieve and analyze.",
    ),
):
    """
    Fetches and analyzes Cloud Run logs for a specified service.
    """
    from crypto_signals.observability import configure_logging
    configure_logging()

    logger.info(f"Starting analysis for service: {service} over the last {hours} hours.")

    from datetime import datetime, timedelta, timezone

    # Import moved inside to allow for better error handling and mocking
    try:
        from google.cloud import logging
        from google.cloud.logging_v2.entries import LogEntry as GCPLogEntry
    except ImportError:
        logger.error(
            "Google Cloud Logging client not found. "
            'Please run: poetry install'
        )
        raise typer.Exit(code=1)


    client = logging.Client()

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(hours=hours)

    start_time_str = start_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    end_time_str = end_time.strftime("%Y-%m-%dT%H:%M:%S.%fZ")

    # Construct the filter to get logs for the specified service and time window
    filter_str = (
        f'resource.type="cloud_run_revision" '
        f'resource.labels.service_name="{service}" '
        f'timestamp >= "{start_time_str}" AND timestamp <= "{end_time_str}"'
    )

    logger.info(f"Fetching logs with filter: {filter_str}")

    try:
        # Note: list_entries returns an iterator. We convert it to a list.
        entries: list[GCPLogEntry] = list(client.list_entries(filter_=filter_str))
        logger.info(f"Successfully fetched {len(entries)} log entries.")
        if not entries:
            logger.warning("No log entries found for the specified filter.")
            raise typer.Exit()
    except Exception as e:
        logger.error(f"An error occurred while fetching logs: {e}")
        raise typer.Exit(code=1)

    from collections import Counter
    from pydantic import ValidationError
    from crypto_signals.domain.schemas import LogEntry, ZombieEvent, OrphanEvent

    # --- Parsing and Analysis Logic ---
    parsed_logs: list[LogEntry] = []
    for entry in entries:
        try:
            # Adapt the raw entry to our Pydantic model
            log_data = {
                "severity": entry.severity,
                "timestamp": entry.timestamp,
                "jsonPayload": entry.payload if isinstance(entry.payload, dict) else None,
                "textPayload": entry.payload if isinstance(entry.payload, str) else None,
            }
            parsed_logs.append(LogEntry.model_validate(log_data))
        except (ValidationError, AttributeError) as e:
            logger.warning(f"Skipping malformed log entry. Error: {e}")
            continue

    severity_counts = Counter(log.severity for log in parsed_logs)
    zombie_events: list[ZombieEvent] = []
    orphan_events: list[OrphanEvent] = []

    for log in parsed_logs:
        message = log.effective_message.lower()
        if "zombie" in message:
            if log.json_payload and log.json_payload.context:
                zombie_events.append(ZombieEvent(details=log.json_payload.context))
        elif "orphan" in message:
            if log.json_payload and log.json_payload.context:
                orphan_events.append(OrphanEvent(details=log.json_payload.context))

    # --- Output Rendering ---
    logger.info("--- Log Analysis Summary ---")
    logger.info(f"CRITICAL Errors: {severity_counts.get('CRITICAL', 0)}")
    logger.info(f"ERRORs: {severity_counts.get('ERROR', 0)}")
    logger.info("--------------------------")

    if zombie_events or orphan_events:
        logger.info("--- JSON Report of Specific Events ---")
        report = {
            "zombie_events": [event.model_dump() for event in zombie_events],
            "orphan_events": [event.model_dump() for event in orphan_events],
        }
        import json
        logger.info(json.dumps(report, indent=2))
        logger.info("------------------------------------")


if __name__ == "__main__":
    app()
