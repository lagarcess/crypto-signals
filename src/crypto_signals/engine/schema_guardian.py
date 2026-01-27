import datetime
from typing import Any, List, Type

from google.api_core.exceptions import NotFound
from google.cloud import bigquery
from loguru import logger
from pydantic import BaseModel


class SchemaMismatchError(Exception):
    """Raised when BigQuery schema does not match Pydantic model."""

    pass


class SchemaGuardian:
    """
    Enforces schema parity between Pydantic Models (Source of Truth) and BigQuery Tables.
    """

    # Mapping Pydantic/Python types to BigQuery types
    TYPE_MAPPING = {
        str: "STRING",
        int: "INTEGER",
        float: "FLOAT",
        bool: "BOOLEAN",
        datetime.datetime: "TIMESTAMP",
        datetime.date: "DATE",
    }

    def __init__(self, bq_client: bigquery.Client, strict_mode: bool = True):
        self.client = bq_client
        self.strict_mode = strict_mode

    def validate_schema(self, table_id: str, model: Type[BaseModel]) -> None:
        """
        Validates that the BigQuery table schema matches the Pydantic model.

        Args:
            table_id: Full table ID (project.dataset.table)
            model: Pydantic model class

        Raises:
            SchemaMismatchError: If schema validation fails and strict_mode is True.
        """
        try:
            table = self.client.get_table(table_id)
        except (NotFound, Exception) as e:
            # Catch NotFound specifically; generic Exception retained for legacy V1 compatibility.
            logger.error(f"Failed to fetch table schema for {table_id}: {e}")
            # If table doesn't exist, we can't validate.
            # In a real pipeline, the loader might create it.
            # For now, we assume table exists or let the loader handle the 404.
            # Raising error here to be safe in strict mode.
            raise e

        missing_columns, type_mismatches = self._validate_fields(
            model.model_fields.items(), table.schema
        )

        error_messages = []
        if missing_columns:
            error_messages.append(f"Missing columns: {', '.join(missing_columns)}")
        if type_mismatches:
            error_messages.append(f"Type mismatch: {', '.join(type_mismatches)}")

        if error_messages:
            full_error = f"Schema Validation Failed for {table_id}: " + "; ".join(
                error_messages
            )
            logger.critical(full_error)
            if self.strict_mode:
                raise SchemaMismatchError(full_error)

    def _validate_fields(
        self,
        model_fields: Any,
        bq_schema: List[bigquery.SchemaField],
        parent_path: str = "",
    ) -> tuple[List[str], List[str]]:
        """
        Recursively validate Pydantic fields against BigQuery schema fields.

        Args:
            model_fields: Iterable of (name, FieldInfo) from Pydantic
            bq_schema: List of BigQuery SchemaField objects
            parent_path: Dot-notation path for nested fields (e.g. "user.address")

        Returns:
            Tuple containing (missing_columns, type_mismatches)
        """
        bq_columns = {field.name: field for field in bq_schema}
        missing = []
        mismatches = []

        for name, field_info in model_fields:
            full_name = f"{parent_path}.{name}" if parent_path else name

            # 1. Resolve Type
            python_type = field_info.annotation
            python_type = self._unwrap_type(python_type)

            expected_type, is_nested_model = self._get_bq_type(python_type)

            # 2. Check Existence
            if name not in bq_columns:
                missing.append(f"{full_name} ({expected_type})")
                continue

            bq_field = bq_columns[name]

            # 3. Check Type Compatibility
            if not self._is_compatible(expected_type, bq_field.field_type):
                mismatches.append(
                    f"{full_name}: Expected {expected_type}, Found {bq_field.field_type}"
                )
                continue

            # 4. Recursion for RECORD/STRUCT
            if is_nested_model and expected_type == "RECORD":
                # Recurse using the inner Pydantic model's fields and BQ field's sub-fields
                sub_missing, sub_mismatches = self._validate_fields(
                    python_type.model_fields.items(),
                    bq_field.fields,
                    parent_path=full_name,
                )
                missing.extend(sub_missing)
                mismatches.extend(sub_mismatches)

        return missing, mismatches

    def _is_compatible(self, expected: str, actual: str) -> bool:
        """Helper to allow fuzzy matching (e.g. FLOAT matches NUMERIC)."""
        if expected == actual:
            return True
        if expected == "FLOAT" and actual in ("NUMERIC", "BIGNUMERIC"):
            return True
        return False

    def _unwrap_type(self, py_type: Any) -> Any:
        """Unwraps Optional, List, Union to get the core type."""
        import typing

        # Unwind Optional / Union
        origin = typing.get_origin(py_type)
        if origin is typing.Union:
            args = typing.get_args(py_type)
            for arg in args:
                if arg is not type(None):
                    py_type = arg
                    break

        # Unwind List / Iterable (TODO: Add explicit REPEATED check if strictly enforcing modes)
        # For now, we just want the inner type to match the BQ type
        origin = typing.get_origin(py_type)
        if origin is list or origin is List:
            args = typing.get_args(py_type)
            if args:
                py_type = args[0]
                # Recursively unwrap inner type (e.g. List[Optional[int]])
                py_type = self._unwrap_type(py_type)

        # Note: This logic assumes simple Optional[T] or List[T].
        # Complex Unions (e.g. Union[int, float]) are not fully supported and default to STRING.
        if typing.get_origin(py_type) is typing.Union:
            logger.warning(
                f"Complex Union type detected: {py_type}. Defaulting to STRING validation."
            )

        return py_type

    def _get_bq_type(self, py_type: Any) -> tuple[str, bool]:
        """
        Resolves Python type to BQ string.
        Returns (bq_type_str, is_pydantic_model_bool)
        """
        # Check for Pydantic Model (Nested)
        try:
            # Note: Explicit check for Pydantic V2 BaseModel.
            # Ensure compat layers (V1) appear as subclasses if used.
            if issubclass(py_type, BaseModel):
                return "RECORD", True
        except TypeError:
            pass  # Not a class

        return self.TYPE_MAPPING.get(py_type, "STRING"), False
