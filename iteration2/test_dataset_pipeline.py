"""Run from iteration2 folder: python test_dataset_pipeline.py PATH_TO_ZIP"""
import sys
from planner.case_loader import load_initial_case
from planner.feature_extractor import extract_features
from planner.planner import InvestigationPlanner

if len(sys.argv) != 2:
    raise SystemExit('Usage: python test_dataset_pipeline.py "path\\to\\dataset.zip"')

zip_path = sys.argv[1]
planner = InvestigationPlanner()

for case_id in ("CASE0000001", "CASE0000003"):
    state = load_initial_case(zip_path, case_id)
    before = extract_features(state)
    assert state.step_count == 0
    assert not state.completed_actions and not state.evidence
    assert before["transaction_amount"] is None
    recommendation = planner.recommend_next_action(state)
    print(f"{case_id}: source={state.case_source}, initial_action={recommendation['recommended_action']}")

# Simulate FAA evidence on an alert case. This is NOT a real FAA tool response.
state = load_initial_case(zip_path, "CASE0000001")
state.update_after_action("GET_TRANSACTION_DETAILS", {
    "Amount": "50000", "Transaction_Type": "transfer", "Channel": "mobile"
})
after = extract_features(state)
assert after["transaction_amount"] == 50000.0
assert after["done_GET_TRANSACTION_DETAILS"] == 1
print("Step 0 intake and post-FAA feature tests passed.")
