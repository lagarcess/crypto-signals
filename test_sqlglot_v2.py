import sqlglot

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
then = whens[0].args.get("then")
print(f"Insert this type: {type(then.this)}")
for col in then.this.expressions:
    print(f"  Col: {col} (type: {type(col)})")

print(f"Insert expression type: {type(then.expression)}")
for val in then.expression.expressions:
    print(f"  Val: {val} (type: {type(val)})")
