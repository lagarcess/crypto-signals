import sqlglot
from sqlglot import exp

sql = """
    MERGE fact T
    USING stg S
    ON T.id = S.id
    WHEN NOT MATCHED THEN
        INSERT (id, val)
        VALUES (S.id, S.val)
"""

expression = sqlglot.parse_one(sql, read="bigquery")
whens = expression.args.get("whens")
for when in whens:
    then = when.args.get("then")
    if isinstance(then, exp.Insert):
        print(f"Insert this type: {type(then.this)}")
        for col in then.this.expressions:
            print(f"  Col: {col} (type: {type(col)})")

        print(f"Insert expression type: {type(then.expression)}")
        for val in then.expression.expressions:
            print(f"  Val: {val} (type: {type(val)})")
