"""Optional FAA report-evidence quality evaluation from the paper's experiment."""

from app.utils.model_output import extract_json_object, generate_with_stage


LIKERT_VALUES = {
    "strongly disagree",
    "disagree",
    "neither agree nor disagree",
    "agree",
    "strongly agree",
}


class EvidenceQualityEvaluator:
    """Rate each report evidence point on the paper's four Likert aspects.

    This is an optional evaluation feature. It is not used as the FAA's
    continue/stop rule and does not produce a fraud probability.
    """

    def __init__(self, gemma_client):
        self.gemma = gemma_client

    def evaluate(self, unfiltered_report):
        if not isinstance(unfiltered_report, str) or not unfiltered_report.strip():
            raise ValueError("A non-empty unfiltered RGA report is required.")

        prompt = f"""
You are evaluating the evidence quality in an FAA investigation report.

For EVERY evidence point in EVERY investigation step, provide a rating on
these four aspects using exactly one of the following Likert values:
strongly disagree, disagree, neither agree nor disagree, agree,
strongly agree.

ASPECTS:
1. impact_on_fraud_suspicion_level: Does this evidence point alter the level
   of fraud suspicion? Both fraud-supporting and legitimacy-supporting
   directions should be scored positively when they alter suspicion.
2. relevant_to_investigation_case: Is the point relevant to this case?
3. providing_new_knowledge: Does the point provide new knowledge or confirm
   previously unsupported knowledge about the case?
4. logical_alignment: Does the point logically align with the rest of the report?

Evaluate each aspect independently. Rate all evidence points, regardless of
whether they support fraud or legitimacy. Do not let the order of evidence
change the rating. Do not invent evidence or omit a point.

Return ONLY valid JSON in this structure:
{{
  "report_evaluation": [
    {{
      "evidence": "Exact evidence point from the report",
      "impact_on_fraud_suspicion_level": "agree",
      "relevant_to_investigation_case": "strongly agree",
      "providing_new_knowledge": "neither agree nor disagree",
      "logical_alignment": "agree"
    }}
  ]
}}

UNFILTERED INVESTIGATION REPORT:
{unfiltered_report}
""".strip()

        result = extract_json_object(
            generate_with_stage(
                self.gemma,
                "Evidence Quality Evaluation",
                prompt,
                max_new_tokens=2400,
            )
        )
        evaluations = result.get("report_evaluation")
        if not isinstance(evaluations, list):
            raise ValueError("report_evaluation must be a list.")

        fields = (
            "impact_on_fraud_suspicion_level",
            "relevant_to_investigation_case",
            "providing_new_knowledge",
            "logical_alignment",
        )
        for index, item in enumerate(evaluations):
            if not isinstance(item, dict) or not isinstance(item.get("evidence"), str):
                raise ValueError(f"Invalid evidence evaluation item at index {index}.")
            for field in fields:
                value = str(item.get(field, "")).strip().lower()
                if value not in LIKERT_VALUES:
                    raise ValueError(
                        f"Invalid Likert value for item {index}, {field}: {value!r}"
                    )
                item[field] = value
        return result
