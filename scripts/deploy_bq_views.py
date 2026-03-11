"""
Deploy BigQuery Views.

Executes the SQL DDL files in scripts/bq/ against the configured GCP project.
Supports environment-based table suffixes (PROD vs DEV/TEST).

Usage:
    poetry run python scripts/deploy_bq_views.py
    poetry run python scripts/deploy_bq_views.py --dry-run
"""

import argparse
import sys
from pathlib import Path

from google.cloud import bigquery
from loguru import logger

# SQL files to deploy, in dependency order
SQL_FILES = [
    "mv_agg_strategy_daily.sql",
    "vw_summary_strategy_performance.sql",
]


def deploy_views(project_id: str, dry_run: bool = False) -> None:
    """Deploy all BQ views/materialized views.

    Args:
        project_id: GCP project ID.
        dry_run: If True, only validate SQL without executing.
    """
    bq_dir = Path(__file__).parent / "bq"
    client = bigquery.Client(project=project_id)

    for sql_file in SQL_FILES:
        sql_path = bq_dir / sql_file
        if not sql_path.exists():
            logger.error(f"SQL file not found: {sql_path}")
            sys.exit(1)

        # Read and inject project_id
        sql = sql_path.read_text().format(project_id=project_id)

        logger.info(f"{'[DRY-RUN] ' if dry_run else ''}Deploying {sql_file}...")

        if dry_run:
            # Validate syntax without executing
            job_config = bigquery.QueryJobConfig(dry_run=True, use_legacy_sql=False)
            try:
                client.query(sql, job_config=job_config)
                logger.info(f"  ✅ {sql_file} — syntax valid")
            except Exception as e:
                logger.error(f"  ❌ {sql_file} — {e}")
                sys.exit(1)
        else:
            try:
                job = client.query(sql)
                job.result()  # Wait for completion
                logger.info(f"  ✅ {sql_file} — deployed successfully")
            except Exception as e:
                logger.error(f"  ❌ {sql_file} — {e}")
                sys.exit(1)

    logger.info(
        "All views deployed successfully." if not dry_run else "Dry-run complete."
    )


def main() -> None:
    """Entry point."""
    parser = argparse.ArgumentParser(description="Deploy BigQuery views for analytics.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate SQL syntax without executing.",
    )
    parser.add_argument(
        "--project-id",
        type=str,
        default=None,
        help="GCP project ID. Defaults to GOOGLE_CLOUD_PROJECT env var.",
    )
    args = parser.parse_args()

    # Resolve project ID
    project_id = args.project_id
    if not project_id:
        import os

        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project_id:
        logger.error("No project ID. Set --project-id or GOOGLE_CLOUD_PROJECT env var.")
        sys.exit(1)

    deploy_views(project_id, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
