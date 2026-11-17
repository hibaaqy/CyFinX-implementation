from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from app.tools.code_execution_tool import query_evidence

CUSTOMER_ID = "C000696"
CURRENT_DEVICE_ID = "D0003337"
HISTORICAL_CUTOFF = "2026-10-12 04:24:55"

# 1. Historical network sessions before the current session
network_sessions_result = query_evidence(
    table="Network_Sessions",
    columns=[
        "Session_ID", "Customer_ID", "Device_ID",
        "Session_start", "Session_end", "City",
        "Latitude", "Longitude", "Network_type"
    ],
    filters=[
        {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID},
        {"column": "Session_start", "operator": "<", "value": HISTORICAL_CUTOFF}
    ],
    order_by="Session_start",
    descending=True,
    limit=500
)

# 2. Historical customer-device links
customer_device_result = query_evidence(
    table="Customer_Device",
    columns=[
        "Customer_Device_ID", "Customer_ID", "Device_ID",
        "First_seen", "Last_seen", "Link_status"
    ],
    filters=[
        {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID},
        {"column": "First_seen", "operator": "<", "value": HISTORICAL_CUTOFF}
    ],
    order_by="First_seen",
    descending=False,
    limit=500
)

# 3. Retrieve device details for historical devices and the current device
device_ids = {
    row.get("Device_ID")
    for row in network_sessions_result.get("rows", [])
    if row.get("Device_ID")
}

device_ids.update(
    row.get("Device_ID")
    for row in customer_device_result.get("rows", [])
    if row.get("Device_ID")
)

device_ids.add(CURRENT_DEVICE_ID)
device_ids = sorted(device_ids)

devices_result = query_evidence(
    table="Devices",
    columns=[
        "Device_ID", "Device_type", "Device_OS",
        "Device_model", "Device_first_seen",
        "Device_last_seen", "Device_status"
    ],
    filters=[
        {"column": "Device_ID", "operator": "IN", "value": device_ids}
    ],
    order_by="Device_ID",
    descending=False,
    limit=500
)

# 4. Historical authentication logs before the current session
auth_logs_result = query_evidence(
    table="Authentication_Logs",
    columns=[
        "Auth_event_ID", "Customer_ID", "Device_ID",
        "Session_ID", "Event_timestamp", "Event_type",
        "Auth_method", "Result", "Attempt_count"
    ],
    filters=[
        {"column": "Customer_ID", "operator": "=", "value": CUSTOMER_ID},
        {"column": "Event_timestamp", "operator": "<", "value": HISTORICAL_CUTOFF}
    ],
    order_by="Event_timestamp",
    descending=True,
    limit=500
)

# Preserve the query results for the FAA Analysis phase
evidence_results = {
    "historical_network_sessions": network_sessions_result,
    "historical_customer_device": customer_device_result,
    "historical_devices": devices_result,
    "historical_authentication_logs": auth_logs_result
}

print(json.dumps(evidence_results, indent=2, default=str))