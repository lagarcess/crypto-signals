
from google.cloud import bigquery
from loguru import logger

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import TradeExecution
from crypto_signals.engine.schema_guardian import SchemaGuardian


def migrate_schema(table_id: str, model) -> None:
    """
    Alters a BigQuery table to add missing columns based on a Pydantic model.

    Args:
        table_id: The full ID of the BigQuery table (project.dataset.table).
        model: The Pydantic model defining the target schema.
    """
    settings = get_settings()
    client = bigquery.Client(project=settings.GOOGLE_CLOUD_PROJECT)
    # Instantiate with strict_mode=False to get the list of missing columns
    # without raising an exception.
    guardian = SchemaGuardian(client, strict_mode=False)

    logger.info(f"Checking schema for table: {table_id}")

    missing_columns, _ = guardian.validate_schema(table_id, model)

    if not missing_columns:
        logger.info("Schema is already up to date.")
        return

    logger.info(f"Found {len(missing_columns)} missing columns. Applying alterations...")

    for column_name, column_type in missing_columns:
        query = f"ALTER TABLE `{table_id}` ADD COLUMN {column_name} {column_type}"
        logger.info(f"Executing: {query}")
        try:
            query_job = client.query(query)
            query_job.result()  # Wait for the job to complete
            logger.info(f"Successfully added column: {column_name}")
        except Exception as e:
            logger.error(f"Failed to add column {column_name}: {e}")


def main():
    """Command-line entry point for schema migration."""
    settings = get_settings()
    table_id = (
        "crypto-signal-bot-481500.crypto_analytics.fact_trades"
        if settings.ENVIRONMENT == "PROD"
        else "crypto-signal-bot-481500.crypto_analytics.fact_trades_test"
    )
    migrate_schema(table_id, TradeExecution)


if __name__ == "__main__":
    main()
