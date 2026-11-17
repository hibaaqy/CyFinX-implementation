import os
import json
from pathlib import Path
from dotenv import load_dotenv
from openai import OpenAI, RateLimitError

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

api_key = os.getenv("OPENROUTER_API_KEY")
if not api_key:
    raise RuntimeError("OPENROUTER_API_KEY was not found in .env")

MODEL = "cohere/north-mini-code:free"

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=api_key
)

investigation_context = {
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
        "Timestamp": "2026-10-12 04:34:16",
        "Amount": 420,
        "Currency": "PKR",
        "Channel": "mobile_app",
        "Transaction_status": "success",
        "Session_ID": "S00142700"
    },
    "previous_analysis_step": {
        "step": 1,
        "findings": [
            "Device D0003337 was recorded as first seen at 01:58:43, approximately 2 hours 26 minutes before the alert-related session started.",
            "Two successful MPIN authentication events were recorded in the alert-related session.",
            "The transaction followed a successful transaction-confirmation authentication event in the same session.",
            "Faisalabad could not previously be assessed as unusual because no historical location baseline had been retrieved.",
            "No failed authentication events appeared in the retrieved records for the alert-related session."
        ],
        "unresolved_questions": [
            "Whether Faisalabad is consistent with the customer's historical locations.",
            "Whether the customer had used device D0003337 before the alert-related session.",
            "Whether successful authentication establishes that the customer personally operated the device.",
            "Whether other unusual device or authentication patterns exist."
        ],
        "decision": "continue",
        "next_lead": "Retrieve historical customer location baseline and device usage logs."
    },
    "information_gathering_step_2": {
        "historical_network_sessions": {
            "returned_records": 22,
            "city_observation": "All 22 returned sessions were in Faisalabad.",
            "device_distribution": {
                "D0003337": 1,
                "D0000912": 9,
                "D0000911": 5,
                "D0000910": 7
            },
            "most_recent_historical_session": {
                "Session_ID": "S00142699",
                "Device_ID": "D0003337",
                "Session_start": "2026-10-12 01:58:43",
                "Session_end": "2026-10-12 02:14:43",
                "City": "Faisalabad"
            }
        },
        "historical_customer_device": {
            "returned_records": 4,
            "devices": [
                {
                    "Device_ID": "D0000910",
                    "First_seen": "2026-05-15 21:57:24",
                    "Last_seen": "2026-07-04 04:40:40",
                    "Link_status": "inactive"
                },
                {
                    "Device_ID": "D0000911",
                    "First_seen": "2026-06-19 21:28:26",
                    "Last_seen": "2026-07-16 17:53:14",
                    "Link_status": "inactive"
                },
                {
                    "Device_ID": "D0000912",
                    "First_seen": "2026-07-22 00:29:01",
                    "Last_seen": "2026-09-23 16:20:37",
                    "Link_status": "active"
                },
                {
                    "Device_ID": "D0003337",
                    "First_seen": "2026-10-12 01:58:43",
                    "Last_seen": "2026-10-12 04:54:55",
                    "Link_status": "active"
                }
            ]
        },
        "historical_devices": [
            {
                "Device_ID": "D0000910",
                "Device_model": "Oppo A78",
                "Device_OS": "Android",
                "Device_status": "inactive"
            },
            {
                "Device_ID": "D0000911",
                "Device_model": "Vivo Y27",
                "Device_OS": "Android",
                "Device_status": "inactive"
            },
            {
                "Device_ID": "D0000912",
                "Device_model": "Oppo A78",
                "Device_OS": "Android",
                "Device_status": "active"
            },
            {
                "Device_ID": "D0003337",
                "Device_model": "Xiaomi Redmi Note 12",
                "Device_OS": "Android",
                "Device_status": "active"
            }
        ],
        "historical_authentication_logs": {
            "returned_records": 26,
            "observation": "All 26 returned records show Result=success.",
            "current_device_binding_events": [
                {
                    "Auth_event_ID": "AUTH00156320",
                    "Event_timestamp": "2026-10-12 01:58:43",
                    "Event_type": "DEVICE_BINDING_REQUEST",
                    "Auth_method": "otp",
                    "Result": "success",
                    "Attempt_count": 1
                },
                {
                    "Auth_event_ID": "AUTH00156321",
                    "Event_timestamp": "2026-10-12 02:03:46",
                    "Event_type": "DEVICE_BINDING_VERIFICATION",
                    "Auth_method": "otp",
                    "Result": "success",
                    "Attempt_count": 1
                }
            ]
        }
    },
    "current_session_step_1_evidence": {
        "Session_ID": "S00142700",
        "Device_ID": "D0003337",
        "Session_start": "2026-10-12 04:24:55",
        "Session_end": "2026-10-12 04:54:55",
        "City": "Faisalabad",
        "Network_type": "mobile_data",
        "ISP": "Jazz",
        "authentication_events": [
            {
                "Auth_event_ID": "AUTH00156322",
                "Event_timestamp": "2026-10-12 04:26:42",
                "Event_type": "LOGIN",
                "Auth_method": "mpin",
                "Result": "success",
                "Attempt_count": 1
            },
            {
                "Auth_event_ID": "AUTH00156323",
                "Event_timestamp": "2026-10-12 04:32:20",
                "Event_type": "TRANSACTION_CONFIRMATION",
                "Auth_method": "mpin",
                "Result": "success",
                "Attempt_count": 1
            }
        ]
    }
}

system_prompt = """
You are the Analysis phase of an FAA (Fraud Analyst Assistant) investigation.

Follow the FAA investigation methodology:
1. Interpret the newly gathered evidence.
2. Integrate it with all previous findings.
3. Assess evidence supporting fraud and evidence supporting legitimacy.
4. Identify what remains unresolved.
5. Decide whether another investigation step is likely to reveal information
   that could change the fraud assessment.

Evaluate evidence using the FAA evidence-quality dimensions:
- Impact on fraud suspicion
- Relevance
- New knowledge
- Logical alignment

Rate each dimension on a 1-to-5 Likert scale and explain the ratings.
Do not calculate an overall score or apply a numeric stopping threshold.

Additional evidence safeguards:
- Do not infer the alert's triggering rules from Alert_type alone.
- Do not claim that no anomalies exist; describe only the records retrieved.
- Matching Device_ID values establish matching recorded identifiers, not
  independent proof of physical hardware identity.
- Do not assume telemetry logs, OTP delivery records, or other unverified
  database tables exist.
Important constraints:
- Do not invent evidence, database records, or events.
- A successful OTP or MPIN event does not prove who physically operated the device.
- Distinguish a newly linked device from a device first used during the alert-related session.
- Consider that the current device had an earlier session before the alert-related session.
- Consider the historical Faisalabad location baseline.
- Do not treat the alert's criticality score as proof of fraud.
- Do not produce a fraud probability.
- Do not decide solely from the number of successful authentication events.
- In the Analysis phase, make the continue/stop decision yourself.
- If continuing, recommend exactly one specific next investigative lead.
- Stop only when further investigation is unlikely to produce evidence that could
  change the fraud assessment.

STRICT OUTPUT REQUIREMENTS:
- Every evidence_findings item MUST contain all seven keys:
  evidence, direction, impact_on_fraud_suspicion, relevance,
  new_knowledge, logical_alignment, rationale.
- Never abbreviate, rename, omit, or invent property names.
- Never use keys such as "pocos".
- All four ratings must be integers from 1 to 5.
- Every JSON property name must be enclosed in double quotes.
- Do not include comments or trailing commas.
- Do not include Markdown fences or text outside the JSON object.
- The output must be parseable by Python json.loads().
- The same Device_ID in two records establishes a matching recorded
  device identifier, not independent proof of physical hardware identity.
- Do not assume OTP delivery logs or push notification records exist
  unless their availability is established.

Return valid JSON only, using this structure:

{
  "step_number": 2,
  "evidence_findings": [
    {
      "evidence": "Specific evidence statement",
      "direction": "fraud_supporting, legitimate_supporting, or neutral_unresolved",
      "impact_on_fraud_suspicion": 1,
      "relevance": 1,
      "new_knowledge": 1,
      "logical_alignment": 1,
      "rationale": "Explanation of the assessment"
    }
  ],
  "integrated_assessment": "Interpretation of all findings so far",
  "unresolved_questions": [
    "Specific unresolved question"
  ],
  "investigation_decision": "continue or stop",
  "decision_reason": "Reason for continuing or stopping",
  "next_investigation_lead": "One specific next lead, or null if stopping"
}
"""

user_prompt = (
    "Perform FAA Analysis Step 2 using the following investigation evidence. "
    "Integrate Step 1 and Step 2 findings. Do not assume facts beyond the data.\n\n"
    + json.dumps(investigation_context, indent=2)
)

try:
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        temperature=0,
        max_tokens=3500,
        response_format={
    "type": "json_schema",
    "json_schema": {
        "name": "faa_analysis_step2",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "step_number": {"type": "integer", "const": 2},
                "evidence_findings": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "evidence": {"type": "string"},
                            "direction": {
                                "type": "string",
                                "enum": [
                                    "fraud_supporting",
                                    "legitimate_supporting",
                                    "neutral_unresolved"
                                ]
                            },
                            "impact_on_fraud_suspicion": {
                                "type": "integer", "minimum": 1, "maximum": 5
                            },
                            "relevance": {
                                "type": "integer", "minimum": 1, "maximum": 5
                            },
                            "new_knowledge": {
                                "type": "integer", "minimum": 1, "maximum": 5
                            },
                            "logical_alignment": {
                                "type": "integer", "minimum": 1, "maximum": 5
                            },
                            "rationale": {"type": "string"}
                        },
                        "required": [
                            "evidence",
                            "direction",
                            "impact_on_fraud_suspicion",
                            "relevance",
                            "new_knowledge",
                            "logical_alignment",
                            "rationale"
                        ]
                    }
                },
                "integrated_assessment": {"type": "string"},
                "unresolved_questions": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "investigation_decision": {
                    "type": "string",
                    "enum": ["continue", "stop"]
                },
                "decision_reason": {"type": "string"},
                "next_investigation_lead": {
                    "type": ["string", "null"]
                }
            },
            "required": [
                "step_number",
                "evidence_findings",
                "integrated_assessment",
                "unresolved_questions",
                "investigation_decision",
                "decision_reason",
                "next_investigation_lead"
            ]
        }
    }
},
        extra_body={"reasoning": {"enabled": False}}
    )
except RateLimitError as exc:
    print("HTTP STATUS:", exc.status_code)
    print("API ERROR:", exc.message)
    if exc.response is not None:
        print("RESPONSE BODY:", exc.response.text)
        for name in ["retry-after", "x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-reset"]:
            print(name + ":", exc.response.headers.get(name))
    raise

content = response.choices[0].message.content
try:
    result = json.loads(content)
except json.JSONDecodeError as exc:
    print("JSON PARSE ERROR:", exc)
    print("FINISH REASON:", response.choices[0].finish_reason)
    print("\nRAW MODEL OUTPUT:\n")
    print(content)
    raise

print("MODEL:", MODEL)
print("\nFAA ANALYSIS STEP 2 RESULT:\n")
print(json.dumps(result, indent=2))