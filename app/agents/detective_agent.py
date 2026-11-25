"""Final fraud/legitimate decision agent in the FAA workflow."""

from app.utils.model_output import extract_json_object, generate_with_stage


class DetectiveAgent:
    def __init__(self, gemma_client):
        self.gemma = gemma_client

    def assess(self, final_rga_report):
        if not isinstance(final_rga_report, str) or not final_rga_report.strip():
            raise ValueError("A non-empty final RGA report is required.")

        prompt = f"""
You are the Detective Agent in the FAA fraud-investigation framework.

Your task is to decide whether the investigated transaction is fraudulent
or legitimate, based ONLY on the concise final report produced by the
Report-Generating Agent (RGA).

Assess fraud-supporting and legitimacy-supporting evidence fairly. Consider
its relevance and how it changes the assessment. Do not invent facts, infer
identity from authentication success, or treat missing records as proof of
fraud or legitimacy. Distinguish observed evidence from interpretation.

Return ONLY one valid JSON object with exactly these fields:
{{
  "decision": "fraudulent or legitimate",
  "reasoning": "Concise explanation grounded in the report",
  "fraud_supporting_evidence": ["..."],
  "legitimacy_supporting_evidence": ["..."],
  "limitations": ["..."]
}}

FINAL RGA REPORT:
{final_rga_report}
""".strip()

        response = generate_with_stage(
            self.gemma, "Detective Agent", prompt, max_new_tokens=800
        )
        return self._validate_result(extract_json_object(response))

    @staticmethod
    def _validate_result(result):
        decision = str(result.get("decision", "")).strip().lower()
        if decision not in {"fraudulent", "legitimate"}:
            raise ValueError(
                f"Invalid Detective Agent decision: {result.get('decision')!r}"
            )

        if not isinstance(result.get("reasoning"), str) or not result["reasoning"].strip():
            raise ValueError("Detective Agent must provide non-empty reasoning.")

        for key in (
            "fraud_supporting_evidence",
            "legitimacy_supporting_evidence",
            "limitations",
        ):
            value = result.get(key)
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValueError(f"Detective Agent field {key!r} must be a list of strings.")

        result["decision"] = decision
        return result
