
import numpy as np

from planner.state_schema import CaseState
from planner.feature_extractor import extract_features

from planner.preprocessing import (
    build_preprocessor,
    transform_features,
)


# CASE 1: Initial alert with no retrieved evidence
case1 = CaseState(
    case_id="C001",
    case_source="alert",
    customer_id="U001",
    transaction_id="T001",
    intake_data={
        "case_priority": "high",
        "alert_type": "unusual_transaction",
        "criticality_score": 85,
    }
)

features1 = extract_features(case1)


# CASE 2: Complaint with transaction evidence
case2 = CaseState(
    case_id="C002",
    case_source="complaint",
    customer_id="U002",
    transaction_id="T002",
    intake_data={
        "case_priority": "medium",
        "complaint_type": "unauthorized_transfer",
    }
)

case2.update_after_action(
    "GET_TRANSACTION_DETAILS",
    {
        "Amount": 50000,
        "Transaction_Type": "transfer",
        "Channel": "mobile",
    }
)

features2 = extract_features(case2)


# CASE 3: Alert with authentication evidence
case3 = CaseState(
    case_id="C003",
    case_source="alert",
    customer_id="U003",
    transaction_id="T003",
    intake_data={
        "case_priority": "high",
        "alert_type": "suspicious_login",
    }
)

case3.update_after_action(
    "CHECK_AUTHENTICATION_LOGS",
    {
        "failed_authentication_events": 3,
        "authentication_attempt_count": 5,
    }
)

features3 = extract_features(case3)


# Fit using illustrative training examples.
training_rows = [features1, features2, features3]

preprocessor, training_df = build_preprocessor(
    training_rows
)

X_train = transform_features(
    preprocessor,
    training_rows
)

assert X_train.shape[0] == 3
assert np.isfinite(X_train).all()

print("PASS: Training feature preprocessing")
print("Input feature count:", training_df.shape[1])
print("Encoded feature count:", X_train.shape[1])


# TEST: Unknown evidence differs from observed zero.
# The missingness indicator must preserve the difference.

initial_features = extract_features(case1)

observed_case = CaseState(
    case_id="C004",
    case_source="alert",
    customer_id="U004"
)

observed_case.update_after_action(
    "CHECK_AUTHENTICATION_LOGS",
    {
        "failed_authentication_events": 0,
        "authentication_attempt_count": 1,
    }
)

observed_features = extract_features(observed_case)

X_comparison = transform_features(
    preprocessor,
    [initial_features, observed_features]
)

assert not np.array_equal(
    X_comparison[0],
    X_comparison[1]
)

print("PASS: Unknown versus observed evidence")


# TEST: New categorical value at inference.
new_case = CaseState(
    case_id="C005",
    case_source="complaint",
    customer_id="U005",
    intake_data={
        "case_priority": "urgent",
        "complaint_type": "new_complaint_category",
    }
)

new_features = extract_features(new_case)

X_new = transform_features(
    preprocessor,
    [new_features]
)

assert X_new.shape[0] == 1
assert X_new.shape[1] == X_train.shape[1]
assert np.isfinite(X_new).all()

print("PASS: Unknown categorical values handled")


print("\nAll preprocessing tests passed.")
