"""Two-stage Report-Generating Agent (RGA) from the FAA framework."""

import json


class ReportGenerator:
    def __init__(self, gemma_client):
        self.gemma = gemma_client

    def generate_unfiltered_report(self, alert, transaction, investigation_steps):
        """Stage 1: report every investigation step and its collected evidence."""
        context = {
            "alert": alert,
            "transaction": transaction,
            "investigation_steps": investigation_steps,
        }
        prompt = f"""
You are the Report-Generating Agent (RGA) in the FAA framework.

STAGE 1 — UNFILTERED INVESTIGATION REPORT

Generate an informative, step-by-step report of the investigation. Include
all investigation steps in order. For every step, use this structure:
- **Step [number]:** [Brief description of the investigative lead]
- **Evidence:**
  - [Concrete evidence collected in this step]

Include the evidence actually retrieved and the analysis findings recorded
for each step. Preserve relevant nulls, empty results, and limitations so
that missing data is not mistaken for a negative finding. Do not invent
records, values, queries, or conclusions. Do not make a final fraud decision.
Use clear language suitable for an investigator reviewing the case.

INVESTIGATION DATA:
{json.dumps(context, indent=2, default=str)}
""".strip()
        return self.gemma.generate(prompt, max_new_tokens=3000).strip()

    def generate_final_report(self, unfiltered_report):
        """Stage 2: extract the evidence most important to legitimacy assessment."""
        prompt = f"""
You are the Report-Generating Agent (RGA) in the FAA framework.

STAGE 2 — CONCISE FINAL INVESTIGATION REPORT

Read the unfiltered investigation report and extract the most important
concrete evidence for assessing the legitimacy of the suspicious transaction.
Present the important evidence clearly, including both evidence that supports
fraud suspicion and evidence that supports legitimacy. Retain material
uncertainties and data limitations. Do not invent or strengthen evidence.
Do not omit a material finding merely because it points in the opposite
direction. Do not make the Detective Agent's final decision.

UNFILTERED REPORT:
{unfiltered_report}
""".strip()
        return self.gemma.generate(prompt, max_new_tokens=1800).strip()

    def generate_reports(self, alert, transaction, investigation_steps):
        unfiltered = self.generate_unfiltered_report(
            alert, transaction, investigation_steps
        )
        if not unfiltered:
            raise ValueError("RGA Stage 1 returned an empty report.")
        final_report = self.generate_final_report(unfiltered)
        if not final_report:
            raise ValueError("RGA Stage 2 returned an empty report.")
        return {
            "unfiltered_report": unfiltered,
            "final_report": final_report,
        }
