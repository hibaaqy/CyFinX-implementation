import json
import pytest

from app.agents.evidence_quality_evaluator import EvidenceQualityEvaluator


class FakeGemma:
    def __init__(self, response):
        self.response = response

    def generate(self, prompt, max_new_tokens=512):
        assert "impact_on_fraud_suspicion_level" in prompt
        return self.response


def test_evidence_quality_evaluator_accepts_likert_values():
    response = json.dumps({
        "report_evaluation": [{
            "evidence": "The recorded device appeared in an earlier session.",
            "impact_on_fraud_suspicion_level": "agree",
            "relevant_to_investigation_case": "strongly agree",
            "providing_new_knowledge": "agree",
            "logical_alignment": "neither agree nor disagree",
        }]
    })
    result = EvidenceQualityEvaluator(FakeGemma(response)).evaluate("Unfiltered report")
    assert len(result["report_evaluation"]) == 1


def test_evidence_quality_evaluator_rejects_non_likert_value():
    response = json.dumps({
        "report_evaluation": [{
            "evidence": "Some evidence.",
            "impact_on_fraud_suspicion_level": "5",
            "relevant_to_investigation_case": "agree",
            "providing_new_knowledge": "agree",
            "logical_alignment": "agree",
        }]
    })
    with pytest.raises(ValueError, match="Invalid Likert value"):
        EvidenceQualityEvaluator(FakeGemma(response)).evaluate("Unfiltered report")
