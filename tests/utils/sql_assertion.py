from typing import List, Optional

import sqlglot
from sqlglot import exp


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


def assert_merge_query_structure(
    sql: str,
    target_table: str,
    source_table: str,
    join_keys: List[str],
    update_columns: Optional[List[str]] = None,
    insert_columns: Optional[List[str]] = None,
    dialect: str = "bigquery",
) -> None:
    """
    Assert that a MERGE query has the correct structure and components.

    Args:
        sql: The generated SQL string.
        target_table: The expected target table name (or ID).
        source_table: The expected source table name (or ID).
        join_keys: List of column names used in the ON clause (e.g. ["id", "ds"]).
        update_columns: List of columns updated in WHEN MATCHED clause.
        insert_columns: List of columns inserted in WHEN NOT MATCHED clause.
        dialect: The SQL dialect to use.
    """
    expression = sqlglot.parse_one(sql, read=dialect)

    if not isinstance(expression, exp.Merge):
        raise AssertionError(f"Expected MERGE statement, got {type(expression)}")

    # 1. Check Target Table
    # sqlglot represents tables as Table(this=Identifier(this='name', quoted=True))
    target = expression.this

    # Strip alias for comparison
    if isinstance(target, exp.Table):
        target.set("alias", None)
    elif isinstance(target, exp.Alias):
        target = target.this

    actual_target = target.sql(dialect=dialect)
    expected_target = sqlglot.parse_one(target_table, read=dialect).sql(dialect=dialect)

    assert actual_target.replace("`", "") == expected_target.replace(
        "`", ""
    ), f"Target table mismatch. Expected {expected_target}, got {actual_target}"

    # 2. Check Source Table (USING clause)
    using = expression.args.get("using")
    if not using:
        raise AssertionError("Missing USING clause")

    # Strip alias for comparison
    if isinstance(using, exp.Table):
        using.set("alias", None)
    elif isinstance(using, exp.Alias):
        using = using.this

    actual_source = using.sql(dialect=dialect)
    expected_source = sqlglot.parse_one(source_table, read=dialect).sql(dialect=dialect)

    assert actual_source.replace("`", "") == expected_source.replace(
        "`", ""
    ), f"Source table mismatch. Expected {expected_source}, got {actual_source}"

    # 3. Check ON Clause (Join Keys)
    on_clause = expression.args.get("on")
    if not on_clause:
        raise AssertionError("Missing ON clause")

    # Collect all equality comparisons in the ON clause
    # We expect T.col = S.col
    found_keys = set()

    for node in on_clause.find_all(exp.EQ):
        left = node.this
        right = node.expression

        cols = []
        if isinstance(left, exp.Column):
            cols.append(left.this.this)
        elif isinstance(left, exp.Identifier):
            cols.append(left.this)

        if isinstance(right, exp.Column):
            cols.append(right.this.this)
        elif isinstance(right, exp.Identifier):
            cols.append(right.this)

        # If both sides refer to the same column (typical join), add it
        if len(cols) == 2 and cols[0] == cols[1]:
            found_keys.add(cols[0])

    for key in join_keys:
        assert key in found_keys, (
            f"Join key '{key}' not found in ON clause equality conditions"
        )

    # 4. Check WHEN Clauses
    whens = expression.args.get("whens")
    if not whens:
        raise AssertionError("Missing WHEN clauses")

    matched_found = False
    not_matched_found = False

    for when in whens:
        is_matched = when.args.get("matched")

        if is_matched:
            matched_found = True
            if update_columns:
                then = when.args.get("then")
                if not isinstance(then, exp.Update):
                    raise AssertionError("WHEN MATCHED should be UPDATE")

                # Check updated columns
                actual_updates = []
                for eq in then.expressions:
                    if isinstance(eq, exp.EQ):
                        col_expr = eq.this
                        if isinstance(col_expr, exp.Column):
                            actual_updates.append(col_expr.this.this)
                        elif isinstance(col_expr, exp.Identifier):
                            actual_updates.append(col_expr.this)

                actual_updates.sort()
                expected_updates = sorted(update_columns)
                assert (
                    actual_updates == expected_updates
                ), f"Update columns mismatch. Expected {expected_updates}, got {actual_updates}"

        else:
            # NOT MATCHED
            not_matched_found = True
            if insert_columns:
                then = when.args.get("then")
                if not isinstance(then, exp.Insert):
                    raise AssertionError("WHEN NOT MATCHED should be INSERT")

                # Check inserted columns
                actual_inserts = []
                # then.this is the schema/columns part e.g. (ds, id, value)
                if hasattr(then, "this") and then.this:
                    cols = then.this.expressions
                    for col in cols:
                        if isinstance(col, exp.Identifier):
                            actual_inserts.append(col.this)
                        elif isinstance(col, exp.Column):
                            actual_inserts.append(col.this.this)

                actual_inserts.sort()
                expected_inserts = sorted(insert_columns)
                assert (
                    actual_inserts == expected_inserts
                ), f"Insert columns mismatch. Expected {expected_inserts}, got {actual_inserts}"

    if update_columns and not matched_found:
        raise AssertionError("Expected WHEN MATCHED clause not found")

    if insert_columns and not not_matched_found:
        raise AssertionError("Expected WHEN NOT MATCHED clause not found")
