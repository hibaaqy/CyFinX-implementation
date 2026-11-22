"""Conditional chart-analysis agent used when an FAA step creates a plot."""


class VisionAgent:
    def __init__(self, gemma_client):
        self.gemma = gemma_client

    def analyze(self, chart_path, case_context, investigative_lead):
        prompt = f"""
You are the Vision Agent supporting a financial fraud investigator.

Analyze the attached chart generated during this specific investigation step.
Explain the chart clearly and identify visible trends, clusters, anomalies,
outliers, and relevant comparisons. Relate the observations to the case and
selected investigative lead. Distinguish what is visibly shown from what
cannot be concluded from the chart. Do not infer customer identity, intent,
or fraud solely from a visual pattern. Do not invent values that are not
visible in the chart.

CASE CONTEXT:
{case_context}

INVESTIGATIVE LEAD:
{investigative_lead}

Return a concise chart interpretation that the Fraud Analyst Assistant can
integrate into its Analysis phase.
""".strip()
        return self.gemma.generate_with_image(
            chart_path,
            prompt,
            max_new_tokens=700,
        )
