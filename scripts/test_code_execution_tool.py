
from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tools.code_execution_tool import run_tool


def show_result(title, request):

    print("\n" + "=" * 60)
    print(title)
    print("=" * 60)

    result = run_tool(request)

    print(json.dumps(
        result,
        indent=4,
        default=str
    ))


if __name__ == "__main__":

    # Test 1: List operational tables
    show_result(
        "TEST 1: AVAILABLE TABLES",
        {
            "action": "list_tables"
        }
    )

    # Test 2: Inspect case table structure
    show_result(
        "TEST 2: CASE TABLE STRUCTURE",
        {
            "action": "describe_table",
            "table": "Cases"
        }
    )

    # Test 3: Retrieve case evidence
    show_result(
        "TEST 3: CASE EVIDENCE RETRIEVAL",
        {
            "action": "query",
            "table": "Cases",
            "columns": [
                "Case_ID",
                "Case_source",
                "Case_status",
                "Case_priority"
            ],
            "limit": 5
        }
    )

    # Test 4: Analyse case distribution
    show_result(
        "TEST 4: CASE SOURCE ANALYSIS",
        {
            "action": "aggregate",
            "table": "Cases",
            "group_by": ["Case_source"],
            "metrics": [
                {
                    "function": "COUNT",
                    "column": "*",
                    "alias": "case_count"
                }
            ]
        }
    )

    print("\nALL TOOL TESTS COMPLETED.")