
from .actions import EVIDENCE_ACTIONS
from .action_masking import get_valid_actions
from .state_schema import CaseState


class InvestigationPlanner:

    def recommend_next_action(
        self,
        state: CaseState,
        available_tools=None
    ) -> dict:

        valid_actions = get_valid_actions(
            state,
            available_tools
        )

        if not valid_actions:
            return {
                "case_id": state.case_id,
                "recommended_action": None,
                "reason": "No valid actions available",
                "planner_type": "rule_baseline",
                "step_count": state.step_count
            }

        # Temporary selection logic
        # Prefer evidence retrieval over workflow actions
        evidence_options = [
            action
            for action in EVIDENCE_ACTIONS
            if action in valid_actions
        ]

        if evidence_options:
            action = evidence_options[0]

        elif "RECOMMEND_REPORT_GENERATION" in valid_actions:
            action = "RECOMMEND_REPORT_GENERATION"

        else:
            action = "RECOMMEND_HUMAN_REVIEW"

        return {
            "case_id": state.case_id,
            "recommended_action": action,
            "planner_type": "rule_baseline",
            "step_count": state.step_count
        }
