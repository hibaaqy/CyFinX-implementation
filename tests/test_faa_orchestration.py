import json

from app.agents.detective_agent import DetectiveAgent
from app.agents.fraud_analyst_assistant import FraudAnalystAssistant
from app.agents.report_generator import ReportGenerator


class FakeTool:
    def list_tables(self):
        return ["Fraud_Alerts", "Transactions"]

    def describe_table(self, table):
        columns = {
            "Fraud_Alerts": [
                "Alert_ID", "Customer_ID", "Transaction_ID", "Alert_timestamp",
                "Alert_type", "Criticality_score", "Criticality_level",
                "Alert_source", "Alert_status",
            ],
            "Transactions": [
                "Transaction_ID", "Customer_ID", "Session_ID", "Beneficiary_ID",
                "Agent_ID", "Receiver_ID", "Timestamp", "Transaction_Type",
                "Amount", "Currency", "Channel", "Transaction_status",
                "Sender_balance_before", "Sender_balance_after",
            ],
        }
        return {"table": table, "columns": [{"name": c} for c in columns[table]]}

    def query_evidence(self, table, columns, filters=None, limit=100, **kwargs):
        if table == "Fraud_Alerts":
            return {"rows": [{
                "Alert_ID": "ALT-TEST", "Customer_ID": "C-TEST",
                "Transaction_ID": "TX-TEST", "Alert_timestamp": "2026-01-01",
                "Alert_type": "test", "Criticality_score": 50,
                "Criticality_level": "medium", "Alert_source": "test",
                "Alert_status": "open",
            }]}
        return {"rows": [{
            "Transaction_ID": "TX-TEST", "Customer_ID": "C-TEST",
            "Session_ID": "S-TEST", "Beneficiary_ID": None, "Agent_ID": None,
            "Receiver_ID": None, "Timestamp": "2026-01-01",
            "Transaction_Type": "payment", "Amount": 100, "Currency": "PKR",
            "Channel": "mobile_app", "Transaction_status": "success",
            "Sender_balance_before": 200, "Sender_balance_after": 100,
        }]}

    def execute_generated_code(self, code, output_dir, timeout_seconds=30, allowed_tables=None):
        return {
            "evidence_results": {"test_query": [{"found": True}]},
            "stdout": "",
            "chart_path": None,
            "generated_code": code,
        }


class FakeGemma:
    def __init__(self):
        self.responses = [
            json.dumps({
                "selected_lead": "Inspect the linked transaction's status.",
                "reason": "Confirm the transaction record before examining more evidence.",
                "tables_to_inspect": ["Transactions"],
                "columns_to_retrieve": {"Transactions": ["Transaction_ID", "Transaction_status"]},
                "expected_insight": "Confirm the recorded transaction status.",
            }),
            "evidence_results = {\"transaction_check\": True}",
            json.dumps({
                "integrated_assessment": "The test evidence was retrieved.",
                "new_findings": [{"finding": "The transaction record exists.", "direction": "neutral_unresolved"}],
                "unresolved_questions": [],
                "investigation_decision": "stop",
                "decision_reason": "The test case has no further test lead.",
                "next_investigative_lead": None,
            }),
            "Unfiltered report: Step 1. Transaction record retrieved.",
            "Final report: The transaction record was retrieved; no fraud conclusion is implied.",
            json.dumps({
                "decision": "legitimate",
                "reasoning": "Mock decision for orchestration test only.",
                "fraud_supporting_evidence": [],
                "legitimacy_supporting_evidence": ["Transaction record exists."],
                "limitations": ["Mock output; no real assessment."],
            }),
        ]

    def generate(self, prompt, max_new_tokens=512):
        return self.responses.pop(0)



def test_complete_faa_cycle_runs_in_order(tmp_path):
    gemma = FakeGemma()
    rga = ReportGenerator(gemma)
    detective = DetectiveAgent(gemma)
    faa = FraudAnalystAssistant(
        gemma_client=gemma,
        report_generator=rga,
        detective_agent=detective,
        evidence_tool=FakeTool(),
        step_output_dir=tmp_path,
    )
    result = faa.investigate("ALT-TEST", max_steps=3)
    assert result["status"] == "completed"
    assert len(result["steps"]) == 1
    assert result["reports"]["final_report"].startswith("Final report:")
    assert result["detective_decision"]["decision"] == "legitimate"


class FakeGemmaContinue:
    def __init__(self):
        self.responses = [
            json.dumps({
                "selected_lead": "Inspect transaction status.",
                "reason": "Verify the transaction record.",
                "tables_to_inspect": ["Transactions"],
                "columns_to_retrieve": {"Transactions": ["Transaction_ID", "Transaction_status"]},
                "expected_insight": "Confirm the status.",
            }),
            "evidence_results = {\"transaction_check\": True}",
            json.dumps({
                "integrated_assessment": "More evidence may be useful.",
                "new_findings": [],
                "unresolved_questions": ["Who operated the device?"],
                "investigation_decision": "continue",
                "decision_reason": "A further lead may change the assessment.",
                "next_investigative_lead": "Review authentication history.",
            }),
        ]

    def generate(self, prompt, max_new_tokens=512):
        return self.responses.pop(0)


def test_safety_cap_pauses_without_rga_or_detective(tmp_path):
    gemma = FakeGemmaContinue()
    faa = FraudAnalystAssistant(
        gemma_client=gemma,
        report_generator=ReportGenerator(gemma),
        detective_agent=DetectiveAgent(gemma),
        evidence_tool=FakeTool(),
        step_output_dir=tmp_path,
    )
    result = faa.investigate("ALT-TEST", max_steps=1)
    assert result["status"] == "paused_max_steps"
    assert "reports" not in result
    assert "detective_decision" not in result
