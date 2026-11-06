
from planner.trajectory_loader import (
    build_training_examples
)


# Illustrative, manually approved trajectories.
# These are only for testing the loader.

trajectories = [
    {
        "case_id": "C001",
        "review_status": "approved",
        "steps": [
            {
                "state_before_action": {
                    "case_id": "C001",
                    "case_source": "complaint",
                    "customer_id": "U001",
                    "transaction_id": "T001",
                    "intake_data": {
                        "complaint_type": "unauthorized_transfer"
                    },
                    "step_count": 0
                },
                "action_taken": "GET_TRANSACTION_DETAILS"
            },
            {
                "state_before_action": {
                    "case_id": "C001",
                    "case_source": "complaint",
                    "customer_id": "U001",
                    "transaction_id": "T001",
                    "intake_data": {
                        "complaint_type": "unauthorized_transfer"
                    },
                    "evidence": {
                        "GET_TRANSACTION_DETAILS": {
                            "Amount": 50000,
                            "Transaction_Type": "transfer"
                        }
                    },
                    "completed_actions": [
                        "GET_TRANSACTION_DETAILS"
                    ],
                    "step_count": 1,
                    "status": "investigating"
                },
                "action_taken": "CHECK_AUTHENTICATION_LOGS"
            }
        ]
    },
    {
        "case_id": "C002",
        "review_status": "approved",
        "steps": [
            {
                "state_before_action": {
                    "case_id": "C002",
                    "case_source": "alert",
                    "customer_id": "U002",
                    "intake_data": {
                        "alert_type": "suspicious_activity"
                    },
                    "step_count": 0
                },
                "action_taken": "CHECK_CUSTOMER_PROFILE"
            }
        ]
    },
    {
        "case_id": "C003",
        "review_status": "pending",
        "steps": [
            {
                "state_before_action": {
                    "case_id": "C003",
                    "case_source": "alert",
                    "customer_id": "U003",
                    "step_count": 0
                },
                "action_taken": "CHECK_DEVICE_HISTORY"
            }
        ]
    }
]


# TEST 1: Convert trajectories into examples
examples = build_training_examples(trajectories)

assert len(examples) == 3
print("PASS: Training examples created")


# TEST 2: Approved cases only
case_ids = {example["case_id"] for example in examples}

assert case_ids == {"C001", "C002"}
print("PASS: Unreviewed cases excluded")


# TEST 3: Correct action labels
assert examples[0]["action"] == "GET_TRANSACTION_DETAILS"
assert examples[1]["action"] == "CHECK_AUTHENTICATION_LOGS"
assert examples[2]["action"] == "CHECK_CUSTOMER_PROFILE"

print("PASS: Action labels extracted")


# TEST 4: Initial and updated evidence
initial_features = examples[0]["features"]
updated_features = examples[1]["features"]

assert initial_features["transaction_amount"] is None
assert updated_features["transaction_amount"] == 50000.0

print("PASS: Step 0 and updated state handled")


# TEST 5: Ground truth must be rejected
leaked = [
    {
        "case_id": "C004",
        "review_status": "approved",
        "steps": [
            {
                "state_before_action": {
                    "case_id": "C004",
                    "case_source": "alert",
                    "customer_id": "U004",
                    "intake_data": {
                        "Ground_Truth": "fraud"
                    },
                    "step_count": 0
                },
                "action_taken": "CHECK_DEVICE_HISTORY"
            }
        ]
    }
]

try:
    build_training_examples(leaked)
    raise AssertionError("Leakage was not detected")
except ValueError as error:
    assert "Forbidden field" in str(error)

print("PASS: Ground truth leakage rejected")


# TEST 6: Invalid actions must be rejected
invalid = [
    {
        "case_id": "C005",
        "review_status": "approved",
        "steps": [
            {
                "state_before_action": {
                    "case_id": "C005",
                    "case_source": "complaint",
                    "customer_id": "U005",
                    "step_count": 0
                },
                "action_taken": "GET_TRANSACTION_DETAILS"
            }
        ]
    }
]

try:
    build_training_examples(invalid)
    raise AssertionError("Invalid action was not detected")
except ValueError as error:
    assert "Invalid action" in str(error)

print("PASS: Invalid action rejected")


print("\nAll trajectory loader tests passed.")
print("Total training examples:", len(examples))
print("Distinct reviewed cases:", len(case_ids))
print("Feature count:", len(examples[0]["features"]))
