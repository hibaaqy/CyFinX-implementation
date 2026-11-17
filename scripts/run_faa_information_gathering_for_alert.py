from pathlib import Path
import sys
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.tools.code_execution_tool import query_evidence

CUSTOMER_ID = "C000696"
SESSION_ID = "S00142700"

evidence_results = {
    "network_sessions": [],
    "devices": [],
    "customer_device": [],
    "authentication_logs": [],
    "notes": []
}

# 1. Retrieve the transaction's network session
network_result = query_evidence(
    table="Network_Sessions",
    columns=[
        "Session_ID",
        "Customer_ID",
        "Device_ID",
        "Session_start",
        "Session_end",
        "IP_address",
        "City",
        "Latitude",
        "Longitude",
        "Network_type",
        "ISP"
    ],
    filters=[
        {"column": "Session_ID", "operator": "=", "value": SESSION_ID},
        {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID}
    ],
    limit=100
)

network_rows = network_result.get("rows", [])
evidence_results["network_sessions"] = network_rows

if not network_rows:
    evidence_results["notes"].append(
        "No matching Network_Sessions records were found."
    )

# 2. Identify devices used in the session
device_ids = sorted({
    row.get("Device_ID")
    for row in network_rows
    if row.get("Device_ID")
})

if not device_ids:
    evidence_results["notes"].append(
        "No Device_ID was available from the matching network sessions."
    )

# 3. Retrieve device details and customer-device links
for device_id in device_ids:

    device_result = query_evidence(
        table="Devices",
        columns=[
            "Device_ID",
            "Device_type",
            "Device_OS",
            "Device_model",
            "Device_first_seen",
            "Device_last_seen",
            "Device_status"
        ],
        filters=[
            {"column": "Device_ID", "operator": "=", "value": device_id}
        ],
        limit=100
    )

    evidence_results["devices"].extend(
        device_result.get("rows", [])
    )

    customer_device_result = query_evidence(
        table="Customer_Device",
        columns=[
            "Customer_Device_ID",
            "Customer_ID",
            "Device_ID",
            "First_seen",
            "Last_seen",
            "Link_status"
        ],
        filters=[
            {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID},
            {"column": "Device_ID", "operator": "=", "value": device_id}
        ],
        limit=100
    )

    evidence_results["customer_device"].extend(
        customer_device_result.get("rows", [])
    )

if device_ids and not evidence_results["devices"]:
    evidence_results["notes"].append(
        "No matching device records were found."
    )

if device_ids and not evidence_results["customer_device"]:
    evidence_results["notes"].append(
        "No customer-device link records were found."
    )

# 4. Retrieve authentication events for the session
authentication_result = query_evidence(
    table="Authentication_Logs",
    columns=[
        "Auth_event_ID",
        "Customer_ID",
        "Device_ID",
        "Session_ID",
        "Event_timestamp",
        "Event_type",
        "Auth_method",
        "Result",
        "Failure_reason",
        "Attempt_count"
    ],
    filters=[
        {"column": "Session_ID", "operator": "=", "value": SESSION_ID},
        {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID}
    ],
    order_by="Event_timestamp",
    limit=100
)

authentication_rows = authentication_result.get("rows", [])
evidence_results["authentication_logs"] = authentication_rows

if not authentication_rows:
    evidence_results["notes"].append(
        "No matching authentication events were found."
    )

print(json.dumps(evidence_results, indent=4, default=str))
