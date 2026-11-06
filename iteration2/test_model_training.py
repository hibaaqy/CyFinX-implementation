
import tempfile
from pathlib import Path

from planner.actions import ALL_ACTIONS
from planner.state_schema import CaseState
from planner.trajectory_loader import build_training_examples

from planner.model_training import (
    train_and_evaluate,
    predict_next_action,
    save_models,
    load_models,
)


# Simulated trajectories for software testing ONLY.
trajectories = []

for i in range(30):

    state = CaseState(
        case_id=f"MOCK{i:03d}",
        case_source="alert" if i % 2 else "complaint",
        customer_id=f"U{i:03d}",
        transaction_id=f"T{i:03d}",
        intake_data={
            "case_priority": (
                "high" if i % 2 else "medium"
            )
        }
    )

    # Step 0: First action
    first_step = {
        "state_before_action": state.to_dict(),
        "action_taken": "GET_TRANSACTION_DETAILS"
    }

    # Simulate FAA retrieving transaction evidence.
    state.update_after_action(
        "GET_TRANSACTION_DETAILS",
        {
            "Amount": 50000 if i % 2 else 2000,
            "Transaction_Type": "transfer"
        }
    )

    # Step 1: Next action
    second_step = {
        "state_before_action": state.to_dict(),
        "action_taken": (
            "CHECK_AUTHENTICATION_LOGS"
            if i % 2
            else "CHECK_DEVICE_HISTORY"
        )
    }

    trajectories.append({
        "case_id": state.case_id,
        "review_status": "approved",
        "steps": [first_step, second_step]
    })


# TEST 1: Convert trajectories into training examples.
# These approvals are artificial, just for testing.
examples = build_training_examples(trajectories)

assert len(examples) == 60

print("PASS: Mock trajectories converted into examples")


# TEST 2: Train both models.
results = train_and_evaluate(
    examples,
    test_size=0.25,
    random_state=42
)

assert set(results["train_case_ids"]).isdisjoint(
    results["test_case_ids"]
)

assert (
    results["train_example_count"]
    + results["test_example_count"]
    == len(examples)
)

assert set(results["models"]) == {
    "logistic_regression",
    "random_forest"
}

print("PASS: Both models trained")
print("PASS: No case overlap between training and test")


# TEST 3: Verify evaluation metrics.
for model_name, metrics in results["metrics"].items():

    assert 0 <= metrics["accuracy"] <= 1
    assert 0 <= metrics["macro_f1"] <= 1
    assert 0 <= metrics["top3_accuracy"] <= 1

    print(f"PASS: {model_name} metrics calculated")


# TEST 4: Predict the first action.
state = CaseState(
    case_id="DEMO",
    case_source="alert",
    customer_id="UDEMO",
    transaction_id="TDEMO"
)

for model_name in results["models"]:

    prediction = predict_next_action(
        state,
        results,
        model_name=model_name
    )

    assert prediction["recommended_action"] in ALL_ACTIONS

    print(
        f"PASS: {model_name} makes a valid "
        "Step 0 recommendation"
    )


# TEST 5: Ensure action masking works with ML.
state.update_after_action(
    "GET_TRANSACTION_DETAILS",
    {"Amount": 50000}
)

next_prediction = predict_next_action(
    state,
    results
)

assert (
    next_prediction["recommended_action"]
    != "GET_TRANSACTION_DETAILS"
)

print("PASS: Action masking applied after evidence retrieval")


# TEST 6: Save and load the trained models.
with tempfile.TemporaryDirectory() as folder:

    path = save_models(
        results,
        Path(folder) / "test_models.joblib"
    )

    restored = load_models(path)

    assert set(restored["models"]) == set(
        results["models"]
    )

    print("PASS: Saving and loading both models")


# TEST 7: Closed cases should not receive actions.
state.status = "closed"

assert (
    predict_next_action(
        state,
        results
    )["recommended_action"] is None
)

print("PASS: Closed case blocks recommendations")


print("\nAll ML training pipeline tests passed.")

print("Synthetic cases:", len({
    e["case_id"] for e in examples
}))

print("Synthetic examples:", len(examples))

print(
    "Training case count:",
    len(results["train_case_ids"])
)

print(
    "Testing case count:",
    len(results["test_case_ids"])
)

print(
    "Metrics are only a software smoke test, "
    "NOT CyFinX research results."
)
