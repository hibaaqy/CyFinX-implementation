import json
import pytest

from app.agents.detective_agent import DetectiveAgent


class FakeGemma:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt, max_new_tokens=512):
        assert "FINAL RGA REPORT" in prompt
        return self.response


def test_detective_agent_validates_decision():
    response = json.dumps({
        "decision": "legitimate",
        "reasoning": "The report contains more legitimacy-supporting evidence.",
        "fraud_supporting_evidence": [],
        "legitimacy_supporting_evidence": ["Recorded evidence A"],
        "limitations": ["Operator identity is not independently established."],
    })
    agent = DetectiveAgent(FakeGemma(response))
    result = agent.assess("Final RGA report text")
    assert result["decision"] == "legitimate"


def test_detective_agent_rejects_invalid_decision():
    response = json.dumps({
        "decision": "uncertain",
        "reasoning": "Insufficient.",
        "fraud_supporting_evidence": [],
        "legitimacy_supporting_evidence": [],
        "limitations": [],
    })
    with pytest.raises(ValueError, match="Invalid Detective Agent decision"):
        DetectiveAgent(FakeGemma(response)).assess("Final RGA report text")
