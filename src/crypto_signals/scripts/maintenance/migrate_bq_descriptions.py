"""
Script to migrate BigQuery table and column descriptions from Pydantic models.

Resolves Issues:
- #303: Remove hardcoded dataset (uses settings.BIGQUERY_DATASET)
- #304: Dynamic model discovery (uses _bq_table_name)
- #305: Fuzzy table lookup (handles table suffixes safely)
"""

import inspect
from typing import List, Optional, Type

import typer
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from loguru import logger
from pydantic import BaseModel

from crypto_signals.config import get_settings
from crypto_signals.domain import schemas


def get_bq_client() -> bigquery.Client:
    """Initialize BigQuery client."""
    settings = get_settings()
    # Assuming standard credentials or environment setup for authentication
    return bigquery.Client(project=settings.GOOGLE_CLOUD_PROJECT)


def find_analytics_models() -> List[Type[BaseModel]]:
    """
    Dynamically discover all Pydantic models in schemas.py that map to BigQuery tables.

    Criteria:
    - Must be a subclass of pydantic.BaseModel
    - Must have a _bq_table_name ClassVar defined
    """
    models = []
    # Inspect all members of schemas module
    for _, obj in inspect.getmembers(schemas):
        if (
            inspect.isclass(obj)
            and issubclass(obj, BaseModel)
            and hasattr(obj, "_bq_table_name")
        ):
            models.append(obj)

    logger.info(
        f"Discovered {len(models)} analytics models: {[m.__name__ for m in models]}"
    )
    return models


def resolve_table_id(client: bigquery.Client, base_table_name: str) -> Optional[str]:
    """
    Resolve the actual BigQuery table ID using fuzzy lookup strategy.

    Strategy:
    1. Construct candidate IDs based on environment (e.g. table_test for DEV).
    2. Check if candidate exists.
    3. If not found and in DEV, fallback to base table name (handle inconsistencies).
    """
    settings = get_settings()
    dataset_id = f"{settings.GOOGLE_CLOUD_PROJECT}.{settings.BIGQUERY_DATASET}"

    candidates = []

    # Logic for suffix:
    # PROD usually has no suffix.
    # TEST usually adds _test.
    # But as per Issue 305, some tables in DEV might NOT have the suffix.

    # Primary candidate
    if settings.TEST_MODE or settings.ENVIRONMENT != "PROD":
        candidates.append(f"{dataset_id}.{base_table_name}_test")
        # Secondary candidate (Issue 305 fix)
        candidates.append(f"{dataset_id}.{base_table_name}")
    else:
        candidates.append(f"{dataset_id}.{base_table_name}")

    for table_id in candidates:
        try:
            client.get_table(table_id)
            logger.info(f"Found table: {table_id}")
            return table_id
        except NotFound:
            # Table doesn't exist, try next candidate
            continue

    logger.warning(f"Could not find table for {base_table_name}. Checked: {candidates}")
    return None


def update_table_description(
    client: bigquery.Client, table_id: str, model: Type[BaseModel]
) -> None:
    """Update BigQuery table and column descriptions from Pydantic model."""
    table = client.get_table(table_id)

    # 1. Update Table Description (from Docstring)
    if model.__doc__:
        doc = inspect.cleandoc(model.__doc__)
        # Only update if changed to avoid unnecessary API calls
        if table.description != doc:
            table.description = doc
            client.update_table(table, ["description"])
            logger.info(f"Updated description for {table_id}")

    # 2. Update Column Descriptions (from Field description)
    # We need to construct a new schema list with updated descriptions
    current_schema = table.schema
    new_schema = []
    changes_count = 0

    model_fields = model.model_fields

    for schema_field in current_schema:
        field_name = schema_field.name

        # Check if field exists in model
        if field_name in model_fields:
            field_info = model_fields[field_name]
            if field_info.description:
                # Update description if different
                if schema_field.description != field_info.description:
                    # Create a new SchemaField with updated description
                    # SchemaField is immutable, so we must recreate
                    new_field = schema_field.to_api_repr()
                    new_field["description"] = field_info.description
                    new_schema_field = bigquery.SchemaField.from_api_repr(new_field)
                    new_schema.append(new_schema_field)
                    changes_count += 1
                    continue

        # Keep existing field if no change
        new_schema.append(schema_field)

    if changes_count > 0:
        table.schema = new_schema
        client.update_table(table, ["schema"])
        logger.info(f"Updated {changes_count} column descriptions for {table_id}")
    else:
        logger.debug(f"No column description changes for {table_id}")


def main_func():
    """Main function logic."""
    logger.info("Starting BigQuery description migration...")

    try:
        client = get_bq_client()
        models = find_analytics_models()

        for model in models:
            base_name = model._bq_table_name
            table_id = resolve_table_id(client, base_name)

            if table_id:
                try:
                    update_table_description(client, table_id, model)
                except Exception as e:
                    logger.error(f"Failed to update {table_id}: {e}")

        logger.info("Migration completed successfully.")

    except Exception as e:
        logger.exception("Migration script failed")
        raise typer.Exit(code=1) from e


def main():
    """Entry point wrapper."""
    typer.run(main_func)


if __name__ == "__main__":
    main()
