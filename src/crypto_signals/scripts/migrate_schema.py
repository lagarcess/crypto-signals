import importlib

import typer
from google.cloud import bigquery
from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import get_settings
from crypto_signals.engine.schema_guardian import SchemaGuardian


def migrate_schema(table_id: str, model: type[BaseModel]) -> None:
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

    add_column_clauses = [
        f"ADD COLUMN `{column_name}` {column_type}"
        for column_name, column_type in missing_columns
    ]
    query = f"ALTER TABLE `{table_id}` {', '.join(add_column_clauses)}"

    logger.info(f"Executing: {query}")
    try:
        query_job = client.query(query)
        query_job.result()  # Wait for the job to complete
        logger.info(f"Successfully added {len(missing_columns)} columns to {table_id}.")
    except Exception as e:
        logger.error(f"Failed to alter table {table_id}: {e}")
        raise


def main(
    table_id: str = typer.Argument(
        ..., help="Full BigQuery table ID (e.g., 'project.dataset.table')"
    ),
    model_name: str = typer.Argument(
        ...,
        help="Fully qualified Pydantic model name (e.g., 'crypto_signals.domain.schemas.TradeExecution')",
    ),
):
    """
    A general-purpose schema migration tool for BigQuery using Pydantic models.
    """
    try:
        module_path, class_name = model_name.rsplit(".", 1)
        module = importlib.import_module(module_path)
        model = getattr(module, class_name)
    except (ImportError, AttributeError) as e:
        logger.error(f"Could not find or import model: {model_name}")
        raise typer.Exit(code=1) from e

    migrate_schema(table_id, model)


if __name__ == "__main__":
    typer.run(main)
