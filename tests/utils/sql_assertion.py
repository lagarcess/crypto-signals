import sqlglot


def assert_sql_equal(actual: str, expected: str, dialect: str = "bigquery") -> None:
    """
    Assert that two SQL strings are semantically equivalent using sqlglot.

    Args:
        actual: The generated SQL string.
        expected: The expected SQL string.
        dialect: The SQL dialect to use for parsing (default: "bigquery").

    Raises:
        AssertionError: If the SQL strings are not semantically equivalent.
    """
    try:
        # Transpile both to a canonical form (strips comments, normalizes case/whitespace)
        # We use sqlglot.transpile which returns a list of strings
        actual_canon = sqlglot.transpile(actual, read=dialect, write=dialect)[0]
        expected_canon = sqlglot.transpile(expected, read=dialect, write=dialect)[0]

        assert actual_canon == expected_canon, (
            f"SQL mismatch!\n"
            f"EXPECTED (Canonical):\n{expected_canon}\n\n"
            f"ACTUAL (Canonical):\n{actual_canon}\n"
        )
    except Exception as e:
        # Fallback for parsing errors or other issues, though we want to catch them
        raise AssertionError(f"SQL comparison failed. Error: {e}") from e
