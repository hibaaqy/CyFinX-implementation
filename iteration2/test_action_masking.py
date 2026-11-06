
from planner.action_masking import (
    get_action_mask,
    get_valid_actions,
    get_mask_reasons
)
from planner.state_schema import CaseState
from planner.planner import InvestigationPlanner


planner = InvestigationPlanner()


# TEST 1: Initial case
case = CaseState(
    case_id="C001",
    case_source="customer_complaint",
    customer_id="U001",
    transaction_id="T001"
)

mask = get_action_mask(case)

assert mask["GET_TRANSACTION_DETAILS"] is True
assert mask["CHECK_RETAILER_ACTIVITY"] is False
assert mask["RECOMMEND_REPORT_GENERATION"] is False
assert mask["RECOMMEND_HUMAN_REVIEW"] is True

print("PASS: Initial case masking")


# TEST 2: First recommendation
result = planner.recommend_next_action(case)

assert result["recommended_action"] == "GET_TRANSACTION_DETAILS"

print("PASS: First action recommendation")


# TEST 3: Simulate FAA evidence retrieval
case.update_after_action(
    action="GET_TRANSACTION_DETAILS",
    evidence_result={
        "Amount": 50000,
        "Transaction_Type": "transfer",
        "Agent_ID": "A001"
    }
)

mask = get_action_mask(case)

assert mask["GET_TRANSACTION_DETAILS"] is False
assert mask["CHECK_RETAILER_ACTIVITY"] is True
assert mask["RECOMMEND_REPORT_GENERATION"] is True

print("PASS: Completed action masked")
print("PASS: Retailer action unlocked")


# TEST 4: Check next recommendation
result = planner.recommend_next_action(case)

assert result["recommended_action"] == "CHECK_TRANSACTION_VELOCITY"

print("PASS: Second action recommendation")


# TEST 5: Unavailable FAA tools
available_tools = {"CHECK_DEVICE_HISTORY"}

result = planner.recommend_next_action(
    case,
    available_tools=available_tools
)

assert result["recommended_action"] == "CHECK_DEVICE_HISTORY"

print("PASS: Unavailable tools masked")


# TEST 6: Missing transaction identifier
case_without_transaction = CaseState(
    case_id="C002",
    case_source="customer_complaint",
    customer_id="U002"
)

mask = get_action_mask(case_without_transaction)

assert mask["GET_TRANSACTION_DETAILS"] is False
assert "CHECK_CUSTOMER_PROFILE" in get_valid_actions(
    case_without_transaction
)

print("PASS: Missing transaction ID handled")


# TEST 7: No customer or transaction ID
empty_case = CaseState(
    case_id="C003",
    case_source="fraud_alert"
)

valid = get_valid_actions(empty_case)

assert valid == ["RECOMMEND_HUMAN_REVIEW"]

print("PASS: Human review fallback")


# TEST 8: Closed case
empty_case.status = "closed"

assert get_valid_actions(empty_case) == []
assert (
    planner.recommend_next_action(empty_case)["recommended_action"]
    is None
)

print("PASS: Closed case blocked")


print("\nAll action masking tests passed.")
