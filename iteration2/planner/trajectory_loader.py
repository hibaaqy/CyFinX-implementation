
import json
from pathlib import Path

from .actions import ALL_ACTIONS
from .action_masking import get_action_mask
from .feature_extractor import extract_features
from .state_schema import CaseState


# Information that must not enter a planner state.
FORBIDDEN_FIELDS = {
    "ground_truth",
    "is_fraud",
    "fraud_type",
    "fraud_label",
    "scenario_id",
    "final_verdict",
    "final_outcome",
}


def check_for_leakage(value):
    """Reject known ground truth and final outcome fields."""

    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in FORBIDDEN_FIELDS:
                raise ValueError(
                    f"Forbidden field in investigation state: {key}"
                )
            check_for_leakage(item)

    elif isinstance(value, list):
        for item in value:
            check_for_leakage(item)


def build_training_examples(trajectories):
    """
    Convert reviewed FAA investigation trajectories into
    state and next action training examples.

    Unreviewed trajectories are excluded.
    """

    examples = []

    for trajectory in trajectories:

        if trajectory.get("review_status") != "approved":
            continue

        case_id = trajectory["case_id"]
        steps = trajectory["steps"]

        for index, step in enumerate(steps):

            state_data = step["state_before_action"]
            action = step["action_taken"]

            # Prevent future or final outcome information
            # from entering the training features.
            check_for_leakage(state_data)

            if action not in ALL_ACTIONS:
                raise ValueError(
                    f"Unknown action in {case_id}: {action}"
                )

            if state_data.get("case_id") != case_id:
                raise ValueError(
                    f"Case ID mismatch in {case_id}"
                )

            state = CaseState(**state_data)

            if state.step_count != index:
                raise ValueError(
                    f"Incorrect step number in {case_id}"
                )

            # Every stored evidence result must come
            # from an action already completed.
            if not set(state.evidence).issubset(
                set(state.completed_actions)
            ):
                raise ValueError(
                    f"Future evidence found in {case_id}"
                )

            mask = get_action_mask(state)

            if not mask.get(action, False):
                raise ValueError(
                    f"Invalid action {action} at "
                    f"step {index} in {case_id}"
                )

            features = extract_features(state)

            examples.append({
                "case_id": case_id,
                "step_count": index,
                "features": features,
                "action": action,
            })

    return examples


def load_trajectory_file(file_path):
    """Load reviewed investigation histories from JSON."""

    path = Path(file_path)

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if isinstance(data, dict):
        trajectories = data["trajectories"]
    elif isinstance(data, list):
        trajectories = data
    else:
        raise ValueError("Invalid trajectory file format")

    return build_training_examples(trajectories)
