from pathlib import Path
import os
import sys
import json

from dotenv import load_dotenv
from openai import OpenAI

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY not found in .env")

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key
)

MODEL = "cohere/north-mini-code:free"

investigation_state = {
    "alert": {
        "Alert_ID": "ALT0000089",
        "Customer_ID": "C000696",
        "Transaction_ID": "TX000114168",
        "Alert_timestamp": "2026-10-12 04:36:37",
        "Alert_type": "new_device_activity",
        "Criticality_score": 88,
        "Criticality_level": "high",
        "Alert_status": "open"
    },
    "transaction": {
        "Transaction_ID": "TX000114168",
        "Customer_ID": "C000696",
        "Session_ID": "S00142700",
        "Timestamp": "2026-10-12 04:34:16",
        "Transaction_Type": "payment",
        "Amount": 420,
        "Currency": "PKR",
        "Channel": "mobile_app",
        "Transaction_status": "success"
    },
    "information_gathering_step_1": {
        "network_sessions": [{
            "Session_ID": "S00142700",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "Session_start": "2026-10-12 04:24:55",
            "Session_end": "2026-10-12 04:54:55",
            "IP_address": "100.76.205.16",
            "City": "Faisalabad",
            "Network_type": "mobile_data",
            "ISP": "Jazz"
        }],
        "devices": [{
            "Device_ID": "D0003337",
            "Device_type": "mobile",
            "Device_OS": "Android",
            "Device_model": "Xiaomi Redmi Note 12",
            "Device_first_seen": "2026-10-12 01:58:43",
            "Device_last_seen": "2026-10-12 04:54:55",
            "Device_status": "active"
        }],
        "customer_device": [{
            "Customer_Device_ID": "CD00003480",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "First_seen": "2026-10-12 01:58:43",
            "Last_seen": "2026-10-12 04:54:55",
            "Link_status": "active"
        }],
        "authentication_logs": [
            {
                "Auth_event_ID": "AUTH00156322",
                "Session_ID": "S00142700",
                "Event_timestamp": "2026-10-12 04:26:42",
                "Event_type": "LOGIN",
                "Auth_method": "mpin",
                "Result": "success",
                "Attempt_count": 1
            },
            {
                "Auth_event_ID": "AUTH00156323",
                "Session_ID": "S00142700",
                "Event_timestamp": "2026-10-12 04:32:20",
                "Event_type": "TRANSACTION_CONFIRMATION",
                "Auth_method": "mpin",
                "Result": "success",
                "Attempt_count": 1
            }
        ]
    },
    "analysis_step_1": {
        "integrated_findings": [
            "Device first_seen precedes session start by 2 hours, 26 minutes and 12 seconds. This does not establish prior customer usage.",
            "Two successful MPIN authentication events occurred during the session.",
            "The transaction followed the transaction-confirmation event.",
            "Faisalabad location cannot be assessed without historical comparison.",
            "No failed authentication events appeared in the retrieved session records."
        ],
        "unresolved_questions": [
            "Did the customer use this device before the recorded first_seen timestamp?",
            "Is Faisalabad a typical location for this customer's transactions?",
            "Could an unauthorized person have obtained the MPIN?",
            "Are there other device or behavioral anomalies?"
        ],
        "investigation_decision": "continue",
        "next_lead": "Retrieve historical customer location baseline and device usage logs to assess whether Faisalabad is typical and to confirm device ownership timeline."
    }
}

schemas = {
    "Network_Sessions": [
        "Session_ID", "Customer_ID", "Device_ID",
        "Session_start", "Session_end", "IP_address",
        "Latitude", "Longitude", "City", "Network_type", "ISP"
    ],
    "Customer_Device": [
        "Customer_Device_ID", "Customer_ID", "Device_ID",
        "First_seen", "Last_seen", "Link_status"
    ],
    "Devices": [
        "Device_ID", "Device_type", "Device_OS", "Device_model",
        "Device_first_seen", "Device_last_seen", "Device_status"
    ],
    "Transactions": [
        "Transaction_ID", "Customer_ID", "Session_ID",
        "Beneficiary_ID", "Agent_ID", "Receiver_ID",
        "Timestamp", "Transaction_Type", "Amount", "Currency",
        "Channel", "Transaction_status",
        "Sender_balance_before", "Sender_balance_after"
    ],
    "Authentication_Logs": [
        "Auth_event_ID", "Customer_ID", "Device_ID", "Session_ID",
        "Event_timestamp", "Event_type", "Auth_method", "Result",
        "Failure_reason", "Attempt_count"
    ]
}

system_prompt = """
You are the Fraud Analyst Assistant in the FAA framework.

You are performing PLANNING for investigation Step 2.

Review the complete investigation state, including:
- Original alert and transaction.
- Evidence retrieved in Information-Gathering Step 1.
- Findings and unresolved questions from Analysis Step 1.
- The next lead suggested by the Analysis phase.

Select ONE investigative lead for the next Information-Gathering
step. The suggested lead is guidance, not a mandatory instruction:
evaluate it against the collected evidence.

For your selected lead:
1. Explain why it is useful.
2. Identify the exact tables and columns required.
3. Explain what insight the evidence may provide.

STRICT RULES:
- Select one lead only.
- Do not plan a fixed sequence of investigations.
- Do not repeat evidence already retrieved unless needed
  for a specific comparison.
- Use only the supplied database schemas.
- Do not invent tables, columns, records, or findings.
- Do not assume Faisalabad is unusual.
- Do not assume the device was unauthorized.
- Do not access ground-truth labels.
- Do not generate or execute code.
- Analysis Step 1 decided to continue, so do not stop here.

Return valid JSON only, with this structure:

{
  "phase": "Planning",
  "step_number": 2,
  "selected_lead": "One investigative lead",
  "reason": "Why it should be investigated",
  "tables_to_inspect": ["table names"],
  "evidence_to_retrieve": [
    {
      "table": "table name",
      "columns": ["exact column names"]
    }
  ],
  "expected_insight": "What the evidence may establish",
  "stop_investigation": false
}
"""

user_prompt = f"""
UPDATED FAA INVESTIGATION STATE:

{json.dumps(investigation_state, indent=2)}

AVAILABLE DATABASE SCHEMAS:

{json.dumps(schemas, indent=2)}

Perform Planning Step 2 and select the next
single investigative lead.
"""

response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0,
    max_tokens=2500,
    response_format={"type": "json_object"},
    extra_body={
        "reasoning": {
            "enabled": False
        }
    }
)

choice = response.choices[0]

print("MODEL:", response.model)
print("FINISH REASON:", choice.finish_reason)
print("USAGE:", response.usage)

content = choice.message.content

if not content:
    print("No Planning response was generated.")
    sys.exit(1)

try:
    result = json.loads(content)

    print("\nFAA PLANNING STEP 2 RESULT:\n")
    print(json.dumps(result, indent=4))

    invalid_tables = [
        table for table in result.get("tables_to_inspect", [])
        if table not in schemas
    ]

    if invalid_tables:
        print("\nWARNING: Unknown tables:", invalid_tables)

    for item in result.get("evidence_to_retrieve", []):
        table = item.get("table")
        if table in schemas:
            invalid_columns = [
                column for column in item.get("columns", [])
                if column not in schemas[table]
            ]
            if invalid_columns:
                print(
                    f"\nWARNING: Invalid columns for {table}:",
                    invalid_columns
                )

except json.JSONDecodeError:
    print("The model returned invalid JSON:")
    print(content)
