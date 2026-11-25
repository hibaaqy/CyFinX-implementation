"""Dynamic FAA investigation loop: Planning -> Information-Gathering -> Analysis."""

import json
from pathlib import Path
from time import perf_counter

from app.tools import code_execution_tool
from app.utils.model_output import (
    extract_json_object,
    extract_python_code,
    generate_with_stage,
)


class FraudAnalystAssistant:
    """Coordinate the FAA investigation one step at a time.

    The FAA LLM chooses each next investigative lead dynamically. The
    configurable max_steps value is only a runtime safety cap: reaching it
    pauses the case and does not force a stop, report, or Detective decision.
    """

    def __init__(
        self,
        gemma_client,
        report_generator,
        detective_agent,
        evidence_tool=None,
        function_calling_tool=None,
        code_retries=2,
        step_output_dir="reports/step_artifacts",
    ):
        self.gemma = gemma_client
        self.report_generator = report_generator
        self.detective_agent = detective_agent
        self.tool = evidence_tool or code_execution_tool
        self.function_calling_tool = function_calling_tool
        self.code_retries = max(0, int(code_retries))
        self.step_output_dir = Path(step_output_dir)

    def investigate(self, alert_id, max_steps=12):
        if not alert_id or not isinstance(alert_id, str):
            raise ValueError("A valid Alert_ID is required.")
        if not isinstance(max_steps, int) or max_steps < 1:
            raise ValueError("max_steps must be a positive integer.")

        alert, transaction = self._load_case(alert_id)
        schemas = self._load_schemas()
        case_context = {"alert": alert, "transaction": transaction}
        steps = []
        stopped_by_faa = False

        for step_number in range(1, max_steps + 1):
            print(f"\n{'=' * 72}\nFAA INVESTIGATION STEP {step_number}\n{'=' * 72}")

            plan = self._planning_phase(
                case_context, schemas, steps, step_number
            )
            print("PLANNING LEAD:", plan["selected_lead"])

            gathering = self._information_gathering_phase(
                case_context, schemas, steps, plan, step_number
            )
            print("INFORMATION-GATHERING: completed")

            vision_analysis = None
            chart_path = gathering.get("chart_path")
            if chart_path:
                if self.function_calling_tool is None:
                    raise RuntimeError(
                        "A chart was generated, but the FAA function-calling tool "
                        "is not configured."
                    )
                vision_analysis = self.function_calling_tool.call(
                    "image_to_text",
                    {
                        "chart_path": chart_path,
                        "case_context": json.dumps(case_context, indent=2, default=str),
                        "investigative_lead": plan["selected_lead"],
                    },
                )
                print("VISION AGENT: chart interpretation completed")
            else:
                print("VISION AGENT: not invoked (no chart was generated)")

            analysis = self._analysis_phase(
                case_context=case_context,
                previous_steps=steps,
                plan=plan,
                gathering=gathering,
                vision_analysis=vision_analysis,
                step_number=step_number,
            )

            report_step = {
                "step_number": step_number,
                "planning": plan,
                "evidence": gathering.get("evidence_results", {}),
                "information_gathering_execution_seconds": gathering.get("execution_seconds"),
                "code_generation_attempts": gathering.get("code_generation_attempts", 1),
                "vision_analysis": vision_analysis,
                "vision_agent_invoked": bool(chart_path),
                "analysis": analysis,
            }
            steps.append(report_step)

            print("ANALYSIS DECISION:", analysis["investigation_decision"].upper())
            print("REASON:", analysis["decision_reason"])

            if analysis["investigation_decision"] == "stop":
                stopped_by_faa = True
                break

        result = {
            "alert_id": alert_id,
            "case_context": case_context,
            "steps": steps,
            "status": "completed" if stopped_by_faa else "paused_max_steps",
        }

        # The FAA paper invokes the RGA and Detective only after the FAA ends
        # the investigation in its Analysis phase. A safety-cap pause is not
        # treated as an FAA stop decision.
        if not stopped_by_faa:
            result["message"] = (
                f"The FAA selected continue after {max_steps} steps. "
                "The case is paused at the configured safety cap; no final "
                "RGA report or Detective decision was generated."
            )
            return result

        reports = self.report_generator.generate_reports(
            alert=alert,
            transaction=transaction,
            investigation_steps=steps,
        )
        result["reports"] = reports
        result["detective_decision"] = self.detective_agent.assess(
            reports["final_report"]
        )
        return result

    def _load_case(self, alert_id):
        alert_result = self.tool.query_evidence(
            table="Fraud_Alerts",
            columns=[
                "Alert_ID", "Customer_ID", "Transaction_ID",
                "Alert_timestamp", "Alert_type", "Criticality_score",
                "Criticality_level", "Alert_source", "Alert_status",
            ],
            filters=[{"column": "Alert_ID", "operator": "=", "value": alert_id}],
            limit=2,
        )
        alert_rows = alert_result.get("rows", [])
        if len(alert_rows) != 1:
            raise ValueError(
                f"Expected one Fraud_Alerts record for {alert_id}; "
                f"found {len(alert_rows)}."
            )
        alert = alert_rows[0]

        transaction_result = self.tool.query_evidence(
            table="Transactions",
            columns=[
                "Transaction_ID", "Customer_ID", "Session_ID",
                "Beneficiary_ID", "Agent_ID", "Receiver_ID", "Timestamp",
                "Transaction_Type", "Amount", "Currency", "Channel",
                "Transaction_status", "Sender_balance_before",
                "Sender_balance_after",
            ],
            filters=[{
                "column": "Transaction_ID",
                "operator": "=",
                "value": alert["Transaction_ID"],
            }],
            limit=2,
        )
        transaction_rows = transaction_result.get("rows", [])
        if len(transaction_rows) != 1:
            raise ValueError(
                "The alert's linked transaction was not found uniquely: "
                f"{alert.get('Transaction_ID')} (found {len(transaction_rows)})."
            )
        transaction = transaction_rows[0]

        if transaction.get("Customer_ID") != alert.get("Customer_ID"):
            raise ValueError(
                "Alert and linked transaction have different Customer_ID values."
            )
        return alert, transaction

    def _load_schemas(self):
        schemas = {}
        for table in self.tool.list_tables():
            schemas[table] = self.tool.describe_table(table)
        return schemas

    def _planning_phase(self, case_context, schemas, previous_steps, step_number):
        prompt = f"""
You are the Fraud Analyst Assistant (FAA) in the FAA framework.

PHASE: PLANNING — INVESTIGATION STEP {step_number}

Review the original alert, linked transaction, and all evidence collected
in previous investigation steps. Use domain knowledge to choose ONE new,
relevant investigative lead and outline how it should be examined.
The investigation is dynamic: do not follow a fixed checklist or repeat a
lead that has already been adequately investigated.

The next phase will generate and execute Python code for the selected lead.
Do not write code or SQL now. Do not retrieve evidence now. Do not make the
final fraud/legitimate decision. Do not use ground-truth or evaluation labels.
Only use tables and columns in the supplied operational schema.

Return ONLY a JSON object with these fields:
{{
  "selected_lead": "One specific investigative lead",
  "reason": "Why this lead may advance the investigation",
  "tables_to_inspect": ["Exact table names"],
  "columns_to_retrieve": {{"ExactTableName": ["ExactColumnName"]}},
  "expected_insight": "What the evidence may establish"
}}

ORIGINAL CASE:
{json.dumps(case_context, indent=2, default=str)}

PREVIOUS INVESTIGATION STEPS:
{json.dumps(previous_steps, indent=2, default=str)}

AVAILABLE OPERATIONAL DATABASE SCHEMA:
{json.dumps(schemas, indent=2, default=str)}
""".strip()

        plan = self._generate_json(prompt, "FAA Planning")
        self._validate_plan(plan, schemas)
        return plan

    @staticmethod
    def _validate_plan(plan, schemas):
        lead = plan.get("selected_lead")
        if not isinstance(lead, str) or not lead.strip():
            raise ValueError("FAA Planning did not provide a selected_lead.")

        tables = plan.get("tables_to_inspect")
        columns = plan.get("columns_to_retrieve")
        if not isinstance(tables, list) or not tables:
            raise ValueError("FAA Planning must select at least one table.")
        if not isinstance(columns, dict):
            raise ValueError("columns_to_retrieve must be a JSON object.")

        for table in tables:
            if table not in schemas:
                raise ValueError(f"FAA Planning selected unknown table: {table}")
            if table not in columns:
                raise ValueError(f"FAA Planning omitted columns_to_retrieve for {table}.")
            requested_columns = columns.get(table, [])
            available_columns = {
                item["name"] for item in schemas[table].get("columns", [])
            }
            if not isinstance(requested_columns, list):
                raise ValueError(f"Columns for {table} must be a list.")
            unknown = set(requested_columns) - available_columns
            if unknown:
                raise ValueError(
                    f"FAA Planning selected unknown columns in {table}: "
                    f"{sorted(unknown)}"
                )

    def _information_gathering_phase(
        self, case_context, schemas, previous_steps, plan, step_number
    ):
        selected_schemas = {
            table: schemas[table] for table in plan["tables_to_inspect"]
        }
        prompt = f"""
You are the Information-Gathering component of the FAA framework.

Generate executable Python code to carry out the EXACT investigative lead
selected during the Planning phase. The code will run in a restricted Python
execution environment with the functions below already available:

query_evidence(table, columns, filters=None, order_by=None,
               descending=False, limit=100)
aggregate_evidence(table, group_by, metrics, filters=None, limit=100)

query_evidence returns a dictionary; retrieve records from result["rows"]
(or result.get("rows", [])). Filters must be a list of dictionaries, e.g.:
[{{"column": "Customer_ID", "operator": "=", "value": "C000696"}}]
Supported operators: =, !=, <, <=, >, >=, LIKE, IS NULL, IS NOT NULL, IN.
The maximum query limit is 500.

CODE REQUIREMENTS:
- Start with `evidence_results = {{}}`.
- Use query_evidence and/or aggregate_evidence only for database access.
- Use only the supplied tables and exact column names.
- Preserve returned rows and add clear notes for empty query results.
- Perform calculations that directly support the selected lead.
- Do not infer or claim facts not established by retrieved data.
- Do not access ground-truth/evaluation data.
- Do not use raw SQL, imports, file access, network access, exec, or eval.
- If a chart materially helps, create NO MORE THAN ONE visualization using
  the preloaded `plt` object. Do not save the chart; the execution tool saves it.
- Do not make a final fraud/legitimate decision.
- The final code must assign a dictionary to `evidence_results`.
- Return Python code only, without Markdown fences or explanation.

SELECTED PLANNING RESULT:
{json.dumps(plan, indent=2, default=str)}

CASE CONTEXT:
{json.dumps(case_context, indent=2, default=str)}

PREVIOUS INVESTIGATION STEPS:
{json.dumps(previous_steps, indent=2, default=str)}

SCHEMAS FOR SELECTED TABLES:
{json.dumps(selected_schemas, indent=2, default=str)}
""".strip()

        code = extract_python_code(
            generate_with_stage(
                self.gemma, "FAA Information-Gathering code", prompt, max_new_tokens=1800
            )
        )
        step_dir = self.step_output_dir / str(case_context["alert"]["Alert_ID"]) / f"step_{step_number}"

        last_error = None
        for attempt in range(self.code_retries + 1):
            try:
                execution_started = perf_counter()
                execution_result = self.tool.execute_generated_code(
                    code=code,
                    output_dir=step_dir,
                    timeout_seconds=30,
                    allowed_tables=plan["tables_to_inspect"],
                )
                execution_result["execution_seconds"] = round(
                    perf_counter() - execution_started, 3
                )
                execution_result["code_generation_attempts"] = attempt + 1
                return execution_result
            except Exception as error:
                last_error = error
                if attempt >= self.code_retries:
                    break
                correction_prompt = f"""
The previous FAA-generated Information-Gathering code failed validation or
execution. Correct the code while preserving the SAME selected investigative
lead. Do not broaden the scope or invent evidence.

ERROR:
{type(error).__name__}: {error}

PREVIOUS CODE:
{code}

Return corrected executable Python code only. Follow the same restricted
execution rules: no imports, no raw SQL, no file/network access, and assign a
dictionary to evidence_results. Use only the supplied selected table schemas.

SELECTED LEAD:
{plan['selected_lead']}

SCHEMAS:
{json.dumps(selected_schemas, indent=2, default=str)}
""".strip()
                code = extract_python_code(
                    generate_with_stage(
                        self.gemma,
                        "FAA Information-Gathering code repair",
                        correction_prompt,
                        max_new_tokens=1800,
                    )
                )

        raise RuntimeError(
            f"FAA Information-Gathering failed after {self.code_retries + 1} "
            f"attempt(s): {last_error}"
        ) from last_error

    def _analysis_phase(
        self, case_context, previous_steps, plan, gathering,
        vision_analysis, step_number,
    ):
        analysis_context = {
            "case": case_context,
            "previous_steps": previous_steps,
            "current_planning": plan,
            "new_evidence": gathering.get("evidence_results", {}),
            "execution_notes": gathering.get("stdout", ""),
            "vision_agent_analysis": vision_analysis,
        }
        prompt = f"""
You are the Fraud Analyst Assistant (FAA) performing the ANALYSIS phase
for investigation step {step_number}.

Interpret the newly gathered evidence and integrate it with the original case
and all previous findings. Distinguish database observations from real-world
conclusions. Assess evidence supporting fraud, evidence supporting legitimacy,
and unresolved/neutral findings fairly. Do not invent facts. Missing records
or null fields are data limitations, not proof of fraud or legitimacy.
Successful authentication does not independently prove who operated a device.

DECISION:
Decide whether another investigative step is needed. Continue if a promising
new direction could produce evidence that may change the fraud assessment.
Stop ONLY when no new investigative direction is likely to change the
assessment. Do not use a numeric evidence threshold or fixed step count.
Do not make the final fraudulent/legitimate decision in this phase.

If continuing, recommend exactly ONE specific next investigative lead.
If stopping, set next_investigative_lead to null.

Return ONLY valid JSON:
{{
  "integrated_assessment": "Interpretation integrating old and new evidence",
  "new_findings": [
    {{"finding": "Concrete finding", "direction": "fraud_supporting, legitimate_supporting, or neutral_unresolved"}}
  ],
  "unresolved_questions": ["Specific unresolved question"],
  "investigation_decision": "continue or stop",
  "decision_reason": "Why the investigation should continue or stop",
  "next_investigative_lead": "One lead, or null if stopping"
}}

INVESTIGATION CONTEXT:
{json.dumps(analysis_context, indent=2, default=str)}
""".strip()

        result = self._generate_json(prompt, "FAA Analysis")
        decision = result.get("investigation_decision")
        if decision not in {"continue", "stop"}:
            raise ValueError(
                "FAA Analysis must set investigation_decision to continue or stop."
            )
        if decision == "continue":
            next_lead = result.get("next_investigative_lead")
            if not isinstance(next_lead, str) or not next_lead.strip():
                raise ValueError(
                    "FAA Analysis chose continue but did not provide one next lead."
                )
        else:
            result["next_investigative_lead"] = None
        return result

    def _generate_json(self, prompt, phase_name):
        raw = generate_with_stage(
            self.gemma, phase_name, prompt, max_new_tokens=1600
        )
        try:
            return extract_json_object(raw)
        except ValueError as first_error:
            repair_prompt = f"""
Your previous response for {phase_name} was not a valid JSON object.
Correct it and return ONLY the required JSON object. Do not add commentary.

VALIDATION ERROR:
{first_error}

PREVIOUS RESPONSE:
{raw}
""".strip()
            repaired = generate_with_stage(
                self.gemma, f"{phase_name} JSON repair", repair_prompt, max_new_tokens=1600
            )
            return extract_json_object(repaired)
