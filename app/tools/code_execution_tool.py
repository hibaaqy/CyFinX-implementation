
from pathlib import Path
import sys
import re
import sqlite3

# Make the project root available for imports
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.database.connection import OPERATIONAL_DB_PATH
from app.database.models import Base


# Only registered operational tables can be accessed.
ALLOWED_TABLES = {
    table.name: {
        column.name for column in table.columns
    }
    for table in Base.metadata.sorted_tables
}

ALLOWED_OPERATORS = {
    "=", "!=", "<", "<=", ">", ">=", "LIKE",
    "IS NULL", "IS NOT NULL", "IN"
}

ALLOWED_AGGREGATIONS = {
    "COUNT", "SUM", "AVG", "MIN", "MAX"
}


def connect_readonly():
    """Open the operational database in read-only mode."""

    if not OPERATIONAL_DB_PATH.exists():
        raise FileNotFoundError(
            f"Database not found: {OPERATIONAL_DB_PATH}"
        )

    uri = OPERATIONAL_DB_PATH.resolve().as_uri() + "?mode=ro"

    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row

    # Prevent database modifications through this connection.
    connection.execute("PRAGMA query_only = ON")

    return connection


def validate_table(table):
    if table not in ALLOWED_TABLES:
        raise ValueError(f"Table not permitted: {table}")


def validate_column(table, column):
    validate_table(table)

    if column not in ALLOWED_TABLES[table]:
        raise ValueError(
            f"Column '{column}' does not exist in '{table}'"
        )


def quote_identifier(name):
    return '"' + name.replace('"', '""') + '"'


def list_tables():
    """List available operational evidence tables."""

    return sorted(ALLOWED_TABLES.keys())


def describe_table(table):
    """Return the columns and relationships of a table."""

    validate_table(table)

    with connect_readonly() as connection:

        rows = connection.execute(
            f"PRAGMA table_info({quote_identifier(table)})"
        ).fetchall()

        foreign_keys = connection.execute(
            f"PRAGMA foreign_key_list({quote_identifier(table)})"
        ).fetchall()

    return {
        "table": table,
        "columns": [
            {
                "name": row["name"],
                "type": row["type"],
                "primary_key": bool(row["pk"]),
                "nullable": not bool(row["notnull"])
                and not bool(row["pk"])
            }
            for row in rows
        ],
        "foreign_keys": [
            {
                "column": row["from"],
                "referenced_table": row["table"],
                "referenced_column": row["to"]
            }
            for row in foreign_keys
        ]
    }


def build_filters(table, filters):
    """Build parameterized SQL conditions."""

    conditions = []
    parameters = []

    for item in filters or []:

        column = item["column"]
        operator = item["operator"].upper()
        value = item.get("value")

        validate_column(table, column)

        if operator not in ALLOWED_OPERATORS:
            raise ValueError(
                f"Unsupported filter operator: {operator}"
            )

        identifier = quote_identifier(column)

        if operator == "IS NULL":
            conditions.append(f"{identifier} IS NULL")

        elif operator == "IS NOT NULL":
            conditions.append(f"{identifier} IS NOT NULL")

        elif operator == "IN":

            if not isinstance(value, list) or not value:
                raise ValueError(
                    "IN requires a non-empty list of values."
                )

            if len(value) > 200:
                raise ValueError("Too many IN values.")

            placeholders = ", ".join("?" for _ in value)

            conditions.append(
                f"{identifier} IN ({placeholders})"
            )

            parameters.extend(value)

        else:

            if value is None:
                raise ValueError(
                    "Use IS NULL or IS NOT NULL for null values."
                )

            conditions.append(
                f"{identifier} {operator} ?"
            )

            parameters.append(value)

    where_clause = ""

    if conditions:
        where_clause = " WHERE " + " AND ".join(conditions)

    return where_clause, parameters


def query_evidence(
    table,
    columns,
    filters=None,
    order_by=None,
    descending=False,
    limit=100
):
    """Retrieve selected evidence records from an operational table."""

    validate_table(table)

    if not columns:
        raise ValueError("Specify at least one column.")

    for column in columns:
        validate_column(table, column)

    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("Limit must be between 1 and 500.")

    if order_by:
        validate_column(table, order_by)

    where_clause, parameters = build_filters(table, filters)

    selected_columns = ", ".join(
        quote_identifier(column) for column in columns
    )

    sql = (
        f"SELECT {selected_columns} "
        f"FROM {quote_identifier(table)}"
        f"{where_clause}"
    )

    if order_by:
        direction = "DESC" if descending else "ASC"
        sql += f" ORDER BY {quote_identifier(order_by)} {direction}"

    sql += " LIMIT ?"
    parameters.append(limit)

    with connect_readonly() as connection:
        rows = connection.execute(sql, parameters).fetchall()

    return {
        "table": table,
        "columns": columns,
        "returned_records": len(rows),
        "rows": [dict(row) for row in rows]
    }


def aggregate_evidence(
    table,
    group_by,
    metrics,
    filters=None,
    limit=100
):
    """Calculate grouped statistics from operational evidence."""

    validate_table(table)

    for column in group_by:
        validate_column(table, column)

    if not metrics:
        raise ValueError("Specify at least one metric.")

    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError("Limit must be between 1 and 500.")

    expressions = [
        quote_identifier(column)
        for column in group_by
    ]

    for metric in metrics:

        function = metric["function"].upper()
        column = metric.get("column")
        alias = metric.get("alias")

        if function not in ALLOWED_AGGREGATIONS:
            raise ValueError(
                f"Unsupported aggregation: {function}"
            )

        if not alias or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,49}", alias
        ):
            raise ValueError("Invalid metric alias.")

        if function == "COUNT" and column == "*":
            expression = "COUNT(*)"

        else:
            validate_column(table, column)

            expression = (
                f"{function}({quote_identifier(column)})"
            )

        expressions.append(
            f"{expression} AS {quote_identifier(alias)}"
        )

    where_clause, parameters = build_filters(table, filters)

    sql = (
        "SELECT " + ", ".join(expressions)
        + f" FROM {quote_identifier(table)}"
        + where_clause
    )

    if group_by:
        sql += " GROUP BY " + ", ".join(
            quote_identifier(column)
            for column in group_by
        )

    sql += f" LIMIT {limit}"

    with connect_readonly() as connection:
        rows = connection.execute(sql, parameters).fetchall()

    return {
        "table": table,
        "group_by": group_by,
        "results": [dict(row) for row in rows]
    }


def run_tool(request):
    """Dispatch an FAA tool request to an approved operation."""

    action = request.get("action")

    if action == "list_tables":
        return list_tables()

    if action == "describe_table":
        return describe_table(request["table"])

    if action == "query":
        return query_evidence(
            table=request["table"],
            columns=request["columns"],
            filters=request.get("filters"),
            order_by=request.get("order_by"),
            descending=request.get("descending", False),
            limit=request.get("limit", 100)
        )

    if action == "aggregate":
        return aggregate_evidence(
            table=request["table"],
            group_by=request.get("group_by", []),
            metrics=request["metrics"],
            filters=request.get("filters"),
            limit=request.get("limit", 100)
        )

    raise ValueError(f"Unknown FAA tool action: {action}")
