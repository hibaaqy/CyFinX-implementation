from pathlib import Path
import os
import json
import sys

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY was not found in .env")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key
)

MODEL = "cohere/north-mini-code:free"

alert = {
    "Alert_ID": "ALT0000089",
    "Customer_ID": "C000696",
    "Transaction_ID": "TX000114168",
    "Alert_timestamp": "2026-10-12 04:36:37",
    "Alert_type": "new_device_activity",
    "Criticality_score": 88,
    "Criticality_level": "high",
    "Alert_source": "synthetic_upstream_monitoring",
    "Alert_status": "open"
}

transaction = {
    "Transaction_ID": "TX000114168",
    "Customer_ID": "C000696",
    "Session_ID": "S00142700",
    "Timestamp": "2026-10-12 04:34:16",
    "Transaction_Type": "payment",
    "Amount": 420,
    "Currency": "PKR",
    "Channel": "mobile_app",
    "Transaction_status": "success",
    "Sender_balance_before": 42403.83,
    "Sender_balance_after": 41983.83
}

schemas = {
    "Customer_Device": [
        "Customer_Device_ID", "Customer_ID", "Device_ID",
        "First_seen", "Last_seen", "Link_status"
    ],
    "Authentication_Logs": [
        "Auth_event_ID", "Customer_ID", "Device_ID", "Session_ID",
        "Event_timestamp", "Event_type", "Auth_method", "Result",
        "Failure_reason", "Attempt_count"
    ],
    "Devices": [
        "Device_ID", "Device_type", "Device_OS", "Device_model",
        "Device_first_seen", "Device_last_seen", "Device_status"
    ],
    "Network_Sessions": [
        "Session_ID", "Customer_ID", "Device_ID",
        "Session_start", "Session_end", "IP_address",
        "Latitude", "Longitude", "City", "Network_type", "ISP"
    ],
    "Transactions": [
        "Transaction_ID", "Customer_ID", "Session_ID",
        "Beneficiary_ID", "Agent_ID", "Receiver_ID",
        "Timestamp", "Transaction_Type", "Amount", "Currency",
        "Channel", "Transaction_status",
        "Sender_balance_before", "Sender_balance_after"
    ]
}

system_prompt = """
You are the Fraud Analyst Assistant (FAA) in the FAA framework
for credit card fraud investigations.

You are currently performing the PLANNING phase.

Your task:
1. Review the alert and transaction evidence collected so far.
2. Select ONE promising investigative lead for the next step.
3. Explain why that lead is relevant to assessing possible fraud.
4. Identify the database tables and exact columns needed to
   investigate that lead.
5. State what insight the investigation is expected to provide.

Important guidelines:
- Make your decision from the supplied evidence, not assumptions.
- The alert type is an indication, not proof of fraud.
- Do not assume the transaction amount is unusual without
  historical customer spending evidence.
- No authentication failures have been established yet.
- Do not invent database columns, records, or findings.
- Only select tables and columns from the supplied schemas.
- Do not generate Python or SQL code in this phase.
- Do not execute database queries.
- Do not access ground-truth labels.
- Do not make a final fraud/legitimate decision.
- Select one lead, not a fixed sequence of investigations.

Return valid JSON only, using this structure:

{
  "phase": "Planning",
  "selected_lead": "One investigative lead",
  "reason": "Why this lead should be investigated",
  "tables_to_inspect": ["table names"],
  "evidence_to_retrieve": ["specific evidence fields"],
  "expected_insight": "What the evidence may establish",
  "stop_investigation": false
}
"""

user_prompt = f"""
CURRENT INVESTIGATION

Alert evidence:
{json.dumps(alert, indent=2)}

Linked transaction evidence:
{json.dumps(transaction, indent=2)}

Available database schemas:
{json.dumps(schemas, indent=2)}

This is the initial evidence for this investigation.
No additional investigative evidence has been collected yet.

Perform the FAA Planning phase and select the next
investigative lead.
"""

response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.1,
    max_tokens=4000
)

choice = response.choices[0]

print("MODEL:", response.model)
print("FINISH REASON:", choice.finish_reason)
print("USAGE:", response.usage)
print("\nFAA PLANNING RESULT:\n")

content = choice.message.content

if not content:
    print("No planning response was generated.")
    print("Finish reason:", choice.finish_reason)
    print("Model:", response.model)
    print("Usage:", response.usage)
    sys.exit(1)

try:
    result = json.loads(content)
    print(json.dumps(result, indent=4))

    invalid_tables = [
        table for table in result.get("tables_to_inspect", [])
        if table not in schemas
    ]

    if invalid_tables:
        print("\nWARNING: Model selected unknown tables:", invalid_tables)

except json.JSONDecodeError:
    print("The model did not return valid JSON:")
    print(content)
