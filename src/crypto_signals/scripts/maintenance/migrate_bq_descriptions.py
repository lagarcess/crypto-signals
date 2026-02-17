"""
Script to migrate BigQuery table and column descriptions from Pydantic models.

Resolves Issues:
- #303: Remove hardcoded dataset (uses settings.BIGQUERY_DATASET)
- #304: Dynamic model discovery (uses _bq_table_name)
- #305: Fuzzy table lookup (handles table suffixes safely)
"""

import inspect
from typing import Any, List, Optional, Type

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


def resolve_table(
    client: bigquery.Client, base_table_name: str
) -> Optional[bigquery.Table]:
    """
    Resolve the actual BigQuery table using fuzzy lookup strategy.

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
            table = client.get_table(table_id)
            logger.info(f"Found table: {table_id}")
            return table
        except NotFound:
            # Table doesn't exist, try next candidate
            continue

    logger.warning(f"Could not find table for {base_table_name}. Checked: {candidates}")
    return None


def _update_schema_recursive(
    bq_schema: List[bigquery.SchemaField], model_fields: dict[str, Any]
) -> tuple[List[bigquery.SchemaField], bool]:
    """
    Recursively update BigQuery schema descriptions from Pydantic model fields.

    Returns:
        tuple: (new_schema_list, has_changes)
    """
    new_schema = []
    has_changes = False

    for schema_field in bq_schema:
        field_name = schema_field.name

        # Check if field exists in model
        if field_name in model_fields:
            field_info = model_fields[field_name]

            # Handle Nested Fields (RECORD type)
            if schema_field.field_type == "RECORD" and hasattr(
                field_info.annotation, "model_fields"
            ):
                nested_model_fields = field_info.annotation.model_fields
                new_nested_fields, nested_changed = _update_schema_recursive(
                    schema_field.fields, nested_model_fields
                )

                # Check description change for the record field itself
                desc_changed = False
                if (
                    field_info.description
                    and schema_field.description != field_info.description
                ):
                    desc_changed = True

                if nested_changed or desc_changed:
                    new_field = schema_field.to_api_repr()
                    if desc_changed:
                        new_field["description"] = field_info.description
                    new_field["fields"] = [f.to_api_repr() for f in new_nested_fields]
                    new_schema_field = bigquery.SchemaField.from_api_repr(new_field)
                    new_schema.append(new_schema_field)
                    has_changes = True
                    continue

            # Handle Simple Fields
            elif field_info.description:
                if schema_field.description != field_info.description:
                    new_field = schema_field.to_api_repr()
                    new_field["description"] = field_info.description
                    new_schema_field = bigquery.SchemaField.from_api_repr(new_field)
                    new_schema.append(new_schema_field)
                    has_changes = True
                    continue

        # Keep existing field if no change
        new_schema.append(schema_field)

    return new_schema, has_changes


def update_table_description(
    client: bigquery.Client, table: bigquery.Table, model: Type[BaseModel]
) -> None:
    """Update BigQuery table and column descriptions from Pydantic model."""
    fields_to_update = []

    # 1. Update Table Description (from Docstring)
    if model.__doc__:
        doc = inspect.cleandoc(model.__doc__)
        # Only update if changed
        if table.description != doc:
            table.description = doc
            fields_to_update.append("description")

    # 2. Update Column Descriptions (Recursive)
    new_schema, schema_changed = _update_schema_recursive(
        table.schema, model.model_fields
    )

    if schema_changed:
        table.schema = new_schema
        fields_to_update.append("schema")

    if fields_to_update:
        client.update_table(table, fields_to_update)
        logger.info(
            f"Updated {fields_to_update} for {table.project}.{table.dataset_id}.{table.table_id}"
        )
    else:
        logger.debug(f"No description changes for {table.table_id}")


def main_func():
    """Main function logic."""
    logger.info("Starting BigQuery description migration...")

    try:
        client = get_bq_client()
        models = find_analytics_models()

        for model in models:
            base_name = getattr(model, "_bq_table_name", "")
            if not base_name:
                continue
            # Optimally resolve table object directly
            table = resolve_table(client, base_name)

            if table:
                try:
                    update_table_description(client, table, model)
                except Exception as e:
                    logger.error(f"Failed to update {table.table_id}: {e}")

        logger.info("Migration completed successfully.")

    except Exception as e:
        logger.exception("Migration script failed")
        raise typer.Exit(code=1) from e


def main():
    """Entry point wrapper."""
    typer.run(main_func)


if __name__ == "__main__":
    main()
