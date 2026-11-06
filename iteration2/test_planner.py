
from planner.state_schema import CaseState
from planner.planner import InvestigationPlanner


# STEP 0: Case creation
case = CaseState(
    case_id="C001",
    case_source="customer_complaint",
    customer_id="U001",
    transaction_id="T001",
    intake_data={
        "complaint_type": "unauthorized_transfer",
        "reported_amount": 50000
    }
)

planner = InvestigationPlanner()

print("INITIAL STATE:")
print(case.to_dict())

# STEP 1: Planner recommends first action
recommendation = planner.recommend_next_action(case)

print("\nFIRST RECOMMENDATION:")
print(recommendation)

assert (
    recommendation["recommended_action"]
    == "GET_TRANSACTION_DETAILS"
)

# Simulate FAA executing the recommended action
case.update_after_action(
    action=recommendation["recommended_action"],
    evidence_result={
        "amount": 50000,
        "transaction_type": "transfer"
    }
)

# STEP 2: Updated state returns to planner
print("\nUPDATED STATE:")
print(case.to_dict())

next_recommendation = planner.recommend_next_action(case)

print("\nSECOND RECOMMENDATION:")
print(next_recommendation)

assert (
    next_recommendation["recommended_action"]
    != "GET_TRANSACTION_DETAILS"
)

print("\nBasic planner flow test passed.")
