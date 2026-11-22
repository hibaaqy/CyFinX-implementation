import pytest

from app.tools import code_execution_tool as tool


def test_executes_approved_read_only_tool_calls(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tool,
        "query_evidence",
        lambda table, **kwargs: {"rows": [{"Transaction_ID": "T1"}]},
    )
    code = '''
evidence_results = {}
result = query_evidence(
    table="Transactions",
    columns=["Transaction_ID"],
    filters=[],
    limit=10
)
evidence_results["transactions"] = result.get("rows", [])
print(len(evidence_results["transactions"]))
'''
    result = tool.execute_generated_code(code, tmp_path)
    assert result["evidence_results"]["transactions"] == [
        {"Transaction_ID": "T1"}
    ]
    assert result["stdout"].strip() == "1"
    assert result["chart_path"] is None


def test_rejects_imports():
    with pytest.raises(ValueError, match="unsupported syntax"):
        tool.validate_generated_code("import os\nevidence_results = {}")


def test_rejects_dunder_access():
    with pytest.raises(ValueError):
        tool.validate_generated_code("evidence_results = {}\nx = (1).__class__")


def test_saves_one_chart(tmp_path):
    code = '''
evidence_results = {"summary": "chart test"}
plt.figure()
plt.plot([1, 2, 3], [2, 4, 3])
plt.title("Test chart")
'''
    result = tool.execute_generated_code(code, tmp_path)
    assert result["chart_path"] is not None
    assert (tmp_path / "investigation_chart.png").is_file()


def test_rejects_more_than_one_chart(tmp_path):
    code = '''
evidence_results = {}
plt.figure()
plt.figure()
'''
    with pytest.raises(ValueError, match="no more than one visualization"):
        tool.execute_generated_code(code, tmp_path)


def test_generated_code_cannot_query_unselected_table(tmp_path, monkeypatch):
    monkeypatch.setattr(
        tool,
        "query_evidence",
        lambda table, **kwargs: {"rows": []},
    )
    code = '''
evidence_results = {}
result = query_evidence(
    table="Fraud_Alerts",
    columns=["Alert_ID"],
    filters=[],
    limit=5
)
evidence_results["alerts"] = result.get("rows", [])
'''
    with pytest.raises(ValueError, match="not selected during Planning"):
        tool.execute_generated_code(
            code,
            tmp_path,
            allowed_tables=["Transactions"],
        )
