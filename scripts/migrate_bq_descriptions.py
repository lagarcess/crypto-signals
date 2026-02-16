"""
Migration script to backfill BigQuery table and column descriptions.

This script iterates through the Pydantic models and their corresponding
BigQuery tables, updating the descriptions based on the Pydantic Field
annotations and class docstrings.
"""

from typing import List, Tuple, Type

from crypto_signals.config import get_settings
from crypto_signals.domain.schemas import (
    AccountSnapshot,
    AggStrategyDaily,
    ExpiredSignal,
    FactRejectedSignal,
    Position,
    Signal,
    StagingAccount,
    StagingPerformance,
    StagingStrategy,
    StrategyPerformance,
    TradeExecution,
)
from crypto_signals.engine.schema_guardian import SchemaGuardian
from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from loguru import logger
from pydantic import BaseModel


def update_schema_descriptions(
    existing_schema: List[bigquery.SchemaField],
    desired_schema: List[bigquery.SchemaField],
) -> List[bigquery.SchemaField]:
    """Recursively update descriptions in the schema."""
    desired_schema_map = {field.name: field for field in desired_schema}
    new_schema = []
    for existing_field in existing_schema:
        if existing_field.name in desired_schema_map:
            desired_field = desired_schema_map[existing_field.name]

            # Recursive call for nested fields (RECORD type)
            fields = existing_field.fields
            if (
                existing_field.field_type == "RECORD"
                or existing_field.field_type == "STRUCT"
            ) and desired_field.fields:
                fields = update_schema_descriptions(
                    list(existing_field.fields), list(desired_field.fields)
                )

            updated_field = bigquery.SchemaField(
                name=existing_field.name,
                field_type=existing_field.field_type,
                mode=existing_field.mode,
                description=desired_field.description or existing_field.description,
                fields=fields,
                policy_tags=existing_field.policy_tags,
            )
            new_schema.append(updated_field)
        else:
            new_schema.append(existing_field)
    return new_schema


def migrate_descriptions():
    settings = get_settings()
    project_id = settings.GOOGLE_CLOUD_PROJECT
    env_suffix = "" if settings.ENVIRONMENT == "PROD" else "_test"
    dataset = "crypto_analytics"

    bq_client = bigquery.Client(project=project_id)
    guardian = SchemaGuardian(bq_client)

    # List of (Model, Table Name)
    # We include all models mentioned in the issue and discovered in pipelines.
    tables_to_migrate: List[Tuple[Type[BaseModel], str]] = [
        (TradeExecution, f"fact_trades{env_suffix}"),
        (TradeExecution, f"stg_trades_import{env_suffix}"),
        (AggStrategyDaily, f"agg_strategy_daily{env_suffix}"),
        (AggStrategyDaily, f"stg_agg_strategy_daily{env_suffix}"),
        (ExpiredSignal, f"fact_signals_expired{env_suffix}"),
        (ExpiredSignal, f"stg_signals_expired_import{env_suffix}"),
        (FactRejectedSignal, f"fact_rejected_signals{env_suffix}"),
        (FactRejectedSignal, f"stg_rejected_signals{env_suffix}"),
        (AccountSnapshot, f"snapshot_accounts{env_suffix}"),
        (StagingAccount, f"stg_accounts_import{env_suffix}"),
        (StrategyPerformance, f"summary_strategy_performance{env_suffix}"),
        (StagingPerformance, f"stg_performance_import{env_suffix}"),
        (StagingStrategy, "dim_strategies"),
        (StagingStrategy, "stg_strategies_import"),
        # Position and Signal are mentioned but may not have direct BQ tables yet.
        # We include them in case they do exist under these names or are used in other datasets.
        (Position, f"live_positions_archive{env_suffix}"),
        (Signal, f"live_signals_archive{env_suffix}"),
    ]

    for model, table_name in tables_to_migrate:
        table_id = f"{project_id}.{dataset}.{table_name}"
        logger.info(f"Checking {table_id} for migration...")

        try:
            table = bq_client.get_table(table_id)

            # 1. Update Table Description
            table.description = (model.__doc__ or "").strip()

            # 2. Update Column Descriptions
            desired_schema = guardian.generate_schema(model)
            table.schema = update_schema_descriptions(list(table.schema), desired_schema)

            bq_client.update_table(table, ["description", "schema"])
            logger.info(f"Successfully updated descriptions for {table_id}")

        except NotFound:
            logger.debug(f"Table {table_id} not found, skipping.")
        except Exception as e:
            logger.error(f"Failed to migrate {table_id}: {e}")


if __name__ == "__main__":
    migrate_descriptions()
