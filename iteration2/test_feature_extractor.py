
from planner.state_schema import CaseState
from planner.feature_extractor import extract_features


case = CaseState(
    case_id="C001",
    case_source="alert",
    customer_id="U001",
    transaction_id="T001",
    intake_data={
        "case_priority": "high",
        "alert_type": "unusual_transaction",
        "criticality_score": "85",
        "criticality_level": "high"
    }
)


# TEST 1: Initial state
features = extract_features(case)

assert features["step_count"] == 0
assert features["transaction_amount"] is None
assert features["failed_authentication_events"] is None
assert features["device_count"] is None
assert features["done_GET_TRANSACTION_DETAILS"] == 0
assert features["alert_criticality_score"] == 85.0

print("PASS: Step 0 features")


# TEST 2: FAA retrieves transaction details
case.update_after_action(
    "GET_TRANSACTION_DETAILS",
    {
        "Amount": "50000",
        "Transaction_Type": "transfer",
        "Channel": "mobile",
        "Transaction_status": "success",
        "Agent_ID": ""
    }
)

features = extract_features(case)

assert features["transaction_amount"] == 50000.0
assert features["transaction_type"] == "transfer"
assert features["transaction_has_agent"] == 0
assert features["done_GET_TRANSACTION_DETAILS"] == 1
assert features["step_count"] == 1

print("PASS: Transaction features")


# TEST 3: FAA retrieves authentication logs
case.update_after_action(
    "CHECK_AUTHENTICATION_LOGS",
    [
        {
            "Result": "failed",
            "Attempt_count": "2"
        },
        {
            "Result": "failed",
            "Attempt_count": "1"
        },
        {
            "Result": "success",
            "Attempt_count": "1"
        }
    ]
)

features = extract_features(case)

assert features["failed_authentication_events"] == 2
assert features["authentication_attempt_count"] == 4
assert features["done_CHECK_AUTHENTICATION_LOGS"] == 1

print("PASS: Authentication features")


# TEST 4: FAA retrieves device history
case.update_after_action(
    "CHECK_DEVICE_HISTORY",
    {
        "records": [
            {"Device_ID": "D001", "Device_status": "active"},
            {"Device_ID": "D002", "Device_status": "inactive"}
        ],
        "new_device_detected": True
    }
)

features = extract_features(case)

assert features["device_count"] == 2
assert features["inactive_device_count"] == 1
assert features["new_device_detected"] == 1

print("PASS: Device features")


# TEST 5: No network anomalies observed
case.update_after_action(
    "CHECK_NETWORK_SESSIONS",
    [
        {"Session_ID": "S001", "IP_address": "10.0.0.1"},
        {"Session_ID": "S002", "IP_address": "10.0.0.1"}
    ]
)

features = extract_features(case)

assert features["network_session_count"] == 2
assert features["distinct_ip_count"] == 1

print("PASS: Network features")


# TEST 6: Empty evidence is different from unknown
case.update_after_action(
    "CHECK_BIOMETRIC_LOGS",
    []
)

features = extract_features(case)

assert features["biometric_event_count"] == 0
assert features["biometric_failed_attempts"] == 0

# Beneficiary history has not been checked.
assert features["beneficiary_count"] is None

assert features["observed_CHECK_BIOMETRIC_LOGS"] == 1
assert features["observed_CHECK_BENEFICIARY_HISTORY"] == 0

print("PASS: Missing versus empty evidence")


# TEST 7: Ground truth must not enter features
assert "is_fraud" not in features
assert "Fraud_type" not in features
assert "Scenario_ID" not in features

print("PASS: No ground truth leakage")


print("\nAll feature extraction tests passed.")
print("Total features:", len(features))
print("Investigation steps:", case.step_count)
