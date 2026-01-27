# Workflow: Diagnose Cloud Run Logs

This workflow provides a streamlined process for analyzing Cloud Run logs to identify and summarize production errors.

## Command: `/diagnose_logs`

### Description

Fetches, parses, and analyzes Google Cloud Run logs to identify critical errors and specific events like "Zombie" or "Orphan" positions. This command is a wrapper around the `workflow_log_analyzer.py` script.

### Usage

To run the log analysis, simply execute the following command:

```bash
/diagnose_logs
```

### Optional Arguments

-   `--service <service-name>`: The name of the Cloud Run service to analyze. Defaults to `crypto-signals-v2`.
-   `--hours <number-of-hours>`: The number of hours of logs to retrieve and analyze. Defaults to `24`.

### Example

To analyze the logs for the `crypto-signals-v2` service over the last 48 hours, you would run:

```bash
/diagnose_logs --service crypto-signals-v2 --hours 48
```

### Implementation

This command is implemented by the `src/crypto_signals/utils/workflow_log_analyzer.py` script.
