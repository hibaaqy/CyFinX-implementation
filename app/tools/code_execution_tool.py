"""Read-only CyFinX evidence tools and restricted FAA code execution."""

import ast
import io
import json
import math
import signal
import statistics
import threading
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from pathlib import Path

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

# ---------------------------------------------------------------------------
# Restricted Python execution for the FAA Information-Gathering phase.
# This is a project-level restriction layer, not a hardened security sandbox.
# Do not execute untrusted code or use this prototype with production data.
# ---------------------------------------------------------------------------

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "float": float, "int": int, "len": len,
    "list": list, "max": max, "min": min, "range": range, "round": round,
    "set": set, "sorted": sorted, "str": str, "sum": sum, "tuple": tuple,
    "zip": zip, "print": print, "isinstance": isinstance,
}

_SAFE_CALL_NAMES = set(_SAFE_BUILTINS) | {
    "query_evidence", "aggregate_evidence"
}

_SAFE_CALL_ATTRIBUTES = {
    # Mapping and sequence operations
    "get", "items", "keys", "values", "append", "extend", "update",
    "sort", "count", "index", "copy", "lower", "upper", "strip", "split",
    "replace", "startswith", "endswith", "join", "tolist",
    # Pandas constructors and in-memory analysis
    "DataFrame", "Series", "to_datetime", "to_numeric", "concat",
    "crosstab", "isna", "notna", "groupby",
    "agg", "aggregate", "describe", "mean", "median", "min", "max",
    "sum", "count", "value_counts", "sort_values", "to_dict", "head",
    "tail", "reset_index", "rename", "dropna", "fillna", "astype",
    "unique", "nunique", "quantile", "corr", "pivot_table", "round",
    "between",
    # Statistics and math
    "stdev", "variance", "median_low", "median_high", "mode", "sqrt",
    "log", "log10", "ceil", "floor", "fabs",
    # Date/time
    "strptime", "strftime", "isoformat", "date", "total_seconds",
    # Matplotlib (the executor saves the one permitted figure)
    "figure", "subplots", "bar", "barh", "hist", "plot", "scatter",
    "pie", "boxplot", "xlabel", "ylabel", "title", "legend", "grid",
    "tight_layout", "xticks", "yticks", "axhline", "axvline", "show",
    "close", "get_fignums", "set_title", "set_xlabel", "set_ylabel",
    "set_xticks", "set_xticklabels", "tick_params",
    # JSON serialization
    "dumps", "loads",
}

_DENIED_NAMES = {
    "__import__", "eval", "exec", "compile", "open", "input", "globals",
    "locals", "vars", "getattr", "setattr", "delattr", "breakpoint",
    "help", "dir", "memoryview", "type", "object",
}

_ALLOWED_AST_NODES = (
    ast.Module, ast.Expr, ast.Assign, ast.AugAssign, ast.Name, ast.Load,
    ast.Store, ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set,
    ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp,
    ast.comprehension, ast.Call, ast.keyword, ast.Attribute, ast.Subscript,
    ast.Slice, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.If,
    ast.For, ast.IfExp, ast.JoinedStr, ast.FormattedValue, ast.Pass,
    ast.Break, ast.Continue, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv,
    ast.Mod, ast.Pow, ast.USub, ast.UAdd, ast.Not, ast.And, ast.Or, ast.Eq,
    ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn, ast.Is,
    ast.IsNot,
)


def validate_generated_code(code):
    """Reject imports, unsafe builtins, dunder access, and unsupported syntax."""
    if not isinstance(code, str) or not code.strip():
        raise ValueError("The FAA generated no Python code.")
    if len(code) > 25_000:
        raise ValueError("Generated code exceeds the 25,000-character limit.")
    try:
        tree = ast.parse(code, mode="exec")
    except SyntaxError as error:
        raise ValueError(f"Generated Python has a syntax error: {error}") from error
    nodes = list(ast.walk(tree))
    if len(nodes) > 3_000:
        raise ValueError("Generated code is too complex (over 3,000 syntax nodes).")
    for node in nodes:
        if not isinstance(node, _ALLOWED_AST_NODES):
            raise ValueError(
                f"Generated code contains unsupported syntax: {type(node).__name__}"
            )
        if isinstance(node, ast.Name):
            if node.id.startswith("__") or node.id in _DENIED_NAMES:
                raise ValueError(f"Use of restricted name: {node.id}")
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ValueError("Private/dunder attribute access is prohibited.")
        if isinstance(node, ast.Call):
            function = node.func
            if isinstance(function, ast.Name):
                if function.id not in _SAFE_CALL_NAMES:
                    raise ValueError(f"Call to unapproved function: {function.id}")
            elif isinstance(function, ast.Attribute):
                if function.attr not in _SAFE_CALL_ATTRIBUTES:
                    raise ValueError(
                        f"Call to unapproved method/function: {function.attr}"
                    )
            else:
                raise ValueError("Unsupported function call in generated code.")
    return tree


class _ExecutionTimeout(TimeoutError):
    pass


def _run_with_timeout(code_object, namespace, timeout_seconds):
    """Run generated code with a wall-clock timeout where SIGALRM is available."""
    if (
        hasattr(signal, "SIGALRM")
        and threading.current_thread() is threading.main_thread()
    ):
        previous_handler = signal.getsignal(signal.SIGALRM)

        def timeout_handler(signum, frame):
            raise _ExecutionTimeout(
                f"Generated code exceeded {timeout_seconds} seconds."
            )

        signal.signal(signal.SIGALRM, timeout_handler)
        signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
        try:
            exec(code_object, namespace, namespace)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)
    else:
        # Colab/Linux uses SIGALRM. This fallback supports local smoke tests.
        exec(code_object, namespace, namespace)


def execute_generated_code(code, output_dir, timeout_seconds=30, allowed_tables=None):
    """Execute FAA-generated Python with approved evidence functions.

    The generated code must assign a dictionary to `evidence_results`.
    At most one matplotlib figure is accepted per investigation step.
    """
    tree = validate_generated_code(code)
    code_object = compile(tree, filename="<faa-generated-code>", mode="exec")
    plt.close("all")
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    allowed_tables = set(
        ALLOWED_TABLES.keys() if allowed_tables is None else allowed_tables
    )

    def restricted_query_evidence(table, *args, **kwargs):
        if table not in allowed_tables:
            raise ValueError(f"Table was not selected during Planning: {table}")
        return query_evidence(table, *args, **kwargs)

    def restricted_aggregate_evidence(table, *args, **kwargs):
        if table not in allowed_tables:
            raise ValueError(f"Table was not selected during Planning: {table}")
        return aggregate_evidence(table, *args, **kwargs)

    namespace = {
        "__builtins__": _SAFE_BUILTINS,
        "query_evidence": restricted_query_evidence,
        "aggregate_evidence": restricted_aggregate_evidence,
        "pd": pd,
        "plt": plt,
        "statistics": statistics,
        "math": math,
        "date": date,
        "datetime": datetime,
        "timedelta": timedelta,
        "json": json,
    }
    captured_output = io.StringIO()
    try:
        with redirect_stdout(captured_output):
            _run_with_timeout(code_object, namespace, timeout_seconds)
        evidence_results = namespace.get("evidence_results")
        if not isinstance(evidence_results, dict):
            raise ValueError(
                "Generated code must assign a dictionary to `evidence_results`."
            )
        figure_numbers = plt.get_fignums()
        if len(figure_numbers) > 1:
            raise ValueError(
                "FAA guideline violation: no more than one visualization "
                "is allowed per investigation step."
            )
        chart_path = None
        if figure_numbers:
            chart_path = output_dir / "investigation_chart.png"
            plt.figure(figure_numbers[0]).savefig(
                chart_path, dpi=160, bbox_inches="tight"
            )
        return {
            "evidence_results": evidence_results,
            "stdout": captured_output.getvalue(),
            "chart_path": str(chart_path) if chart_path else None,
            "generated_code": code,
        }
    finally:
        plt.close("all")
