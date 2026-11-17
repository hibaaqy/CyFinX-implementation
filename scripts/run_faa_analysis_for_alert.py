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

alert = {
    "Alert_ID": "ALT0000089",
    "Customer_ID": "C000696",
    "Transaction_ID": "TX000114168",
    "Alert_timestamp": "2026-10-12 04:36:37",
    "Alert_type": "new_device_activity",
    "Criticality_score": 88,
    "Criticality_level": "high",
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
    "Transaction_status": "success"
}

information_gathering_evidence = {
    "network_sessions": [
        {
            "Session_ID": "S00142700",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "Session_start": "2026-10-12 04:24:55",
            "Session_end": "2026-10-12 04:54:55",
            "IP_address": "100.76.205.16",
            "City": "Faisalabad",
            "Latitude": 31.439944,
            "Longitude": 73.15292,
            "Network_type": "mobile_data",
            "ISP": "Jazz"
        }
    ],
    "devices": [
        {
            "Device_ID": "D0003337",
            "Device_type": "mobile",
            "Device_OS": "Android",
            "Device_model": "Xiaomi Redmi Note 12",
            "Device_first_seen": "2026-10-12 01:58:43",
            "Device_last_seen": "2026-10-12 04:54:55",
            "Device_status": "active"
        }
    ],
    "customer_device": [
        {
            "Customer_Device_ID": "CD00003480",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "First_seen": "2026-10-12 01:58:43",
            "Last_seen": "2026-10-12 04:54:55",
            "Link_status": "active"
        }
    ],
    "authentication_logs": [
        {
            "Auth_event_ID": "AUTH00156322",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "Session_ID": "S00142700",
            "Event_timestamp": "2026-10-12 04:26:42",
            "Event_type": "LOGIN",
            "Auth_method": "mpin",
            "Result": "success",
            "Failure_reason": None,
            "Attempt_count": 1
        },
        {
            "Auth_event_ID": "AUTH00156323",
            "Customer_ID": "C000696",
            "Device_ID": "D0003337",
            "Session_ID": "S00142700",
            "Event_timestamp": "2026-10-12 04:32:20",
            "Event_type": "TRANSACTION_CONFIRMATION",
            "Auth_method": "mpin",
            "Result": "success",
            "Failure_reason": None,
            "Attempt_count": 1
        }
    ]
}

system_prompt = """
You are the Fraud Analyst Assistant (FAA) in the FAA
framework for fraud investigations.

You are performing the ANALYSIS phase.

Review the original alert, transaction, and evidence
retrieved during Information-Gathering Step 1.

VERIFIED TIMING:
- Device_first_seen: 2026-10-12 01:58:43
- Customer_Device.First_seen: 2026-10-12 01:58:43
- Network session start: 2026-10-12 04:24:55
- Transaction timestamp: 2026-10-12 04:34:16
- Alert timestamp: 2026-10-12 04:36:37

The recorded device first-seen timestamp precedes:
- Session start by 2 hours, 26 minutes, 12 seconds.
- Transaction by 2 hours, 35 minutes, 33 seconds.

IMPORTANT EVIDENCE LIMITATIONS:
- Do not say device first_seen matches session start.
- The retrieved evidence does not establish whether the
  customer used this device before the recorded first_seen.
- No historical customer location baseline has been retrieved.
- Do not call Faisalabad a new, unusual, or suspicious
  location without historical comparison evidence.
- Two authentication events were retrieved, both successful.
- Do not claim successful MPIN authentication proves
  the legitimate customer operated the device.
- State only that no failed authentication events appeared
  in the retrieved records for this session.
- Do not invent facts or evidence.

ANALYSIS TASKS:
1. Interpret the new evidence.
2. Integrate it with the original alert and transaction.
3. Identify fraud-supporting evidence.
4. Identify legitimate-supporting evidence.
5. Identify unresolved questions.
6. Evaluate important evidence using four 1-to-5 ratings:
   impact on fraud suspicion, relevance, new knowledge,
   and logical alignment.
7. Decide whether further investigation is needed.

These ratings measure evidence quality, not fraud probability.
Assess evidence supporting both directions fairly.

Continue if an unresolved investigative direction could
provide evidence that changes the assessment.

Stop only if no promising investigative direction remains.

Do not generate code or execute database queries.
Do not access ground-truth labels.
Do not make an unsupported final fraud decision.

Return valid JSON only:

{
  "phase": "Analysis",
  "step_number": 1,
  "integrated_findings": [],
  "unresolved_questions": [],
  "investigation_decision": "continue or stop",
  "next_lead": "One investigative lead, or null",
  "decision_reason": "Reason for continuing or stopping"
}

Each finding must contain:
- finding
- evidence_direction: fraud_supporting, legitimate_supporting,
  or neutral_unresolved
- evidence_quality:
  - impact_on_fraud_suspicion: integer 1 to 5
  - relevance: integer 1 to 5
  - new_knowledge: integer 1 to 5
  - logical_alignment: integer 1 to 5
- rationale
"""

user_prompt = f"""
ORIGINAL ALERT:
{json.dumps(alert, indent=2)}

ORIGINAL TRANSACTION:
{json.dumps(transaction, indent=2)}

INFORMATION-GATHERING STEP 1 EVIDENCE:
{json.dumps(information_gathering_evidence, indent=2)}

Perform the FAA Analysis phase.
Integrate all evidence and decide whether to continue
the investigation or stop.
"""

response = client.chat.completions.create(
    model=MODEL,
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ],
    temperature=0.1,
    max_tokens=3000,
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
    print("No Analysis response was generated.")
    sys.exit(1)

try:
    result = json.loads(content)
    print("\nFAA ANALYSIS RESULT:\n")
    print(json.dumps(result, indent=4))

    if result.get("investigation_decision") not in ["continue", "stop"]:
        print("\nWARNING: Unexpected investigation_decision value.")

except json.JSONDecodeError:
    print("\nThe model did not return valid JSON:")
    print(content)
