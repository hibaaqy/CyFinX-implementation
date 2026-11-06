
from .actions import EVIDENCE_ACTIONS, WORKFLOW_ACTIONS


# Temporary prerequisites until FAA tool contracts are finalized.
ACTION_REQUIREMENTS = {
    "GET_TRANSACTION_DETAILS": {"transaction_id"},
    "CHECK_TRANSACTION_VELOCITY": {"customer_id"},
    "CHECK_DEVICE_HISTORY": {"customer_id"},
    "CHECK_AUTHENTICATION_LOGS": {"customer_id"},
    "CHECK_BENEFICIARY_HISTORY": {"customer_id"},
    "CHECK_KYC_RECORDS": {"customer_id"},
    "CHECK_BIOMETRIC_LOGS": {"customer_id"},
    "CHECK_NETWORK_SESSIONS": {"customer_id"},
    "CHECK_CUSTOMER_COMPLAINTS": {"customer_id"},
    "CHECK_FRAUD_ALERTS": {"customer_id"},
    "CHECK_RETAILER_ACTIVITY": {"agent_id"},
    "CHECK_CUSTOMER_PROFILE": {"customer_id"},
}


def get_action_mask(state, available_tools=None):
    """
    True means an action is allowed.
    False means an action is masked.

    available_tools:
        Optional set of evidence actions implemented by FAA.
        If omitted, all evidence tools are assumed available.
    """

    mask = {}
    attempted = set(
        state.completed_actions + state.failed_actions
    )

    closed_statuses = {
        "closed",
        "completed",
        "awaiting_human_review",
    }

    if state.status in closed_statuses:
        return {
            action: False
            for action in EVIDENCE_ACTIONS + WORKFLOW_ACTIONS
        }

    for action in EVIDENCE_ACTIONS:

        if action in attempted:
            mask[action] = False
            continue

        if available_tools is not None and action not in available_tools:
            mask[action] = False
            continue

        requirements = ACTION_REQUIREMENTS.get(action, set())

        valid = True

        for requirement in requirements:
            if requirement == "agent_id":
                transaction = state.evidence.get(
                    "GET_TRANSACTION_DETAILS", {}
                )
                if not isinstance(transaction, dict):
                    transaction = {}

                agent_id = transaction.get("Agent_ID")

                if not agent_id:
                    valid = False

            elif not getattr(state, requirement, None):
                valid = False

        mask[action] = valid

    # Report generation is permitted after at least
    # one successful evidence retrieval.
    mask["RECOMMEND_REPORT_GENERATION"] = (
        len(state.completed_actions) > 0
    )

    # Human review can be recommended at any active stage.
    mask["RECOMMEND_HUMAN_REVIEW"] = True

    return mask


def get_valid_actions(state, available_tools=None):
    mask = get_action_mask(state, available_tools)

    return [
        action
        for action, allowed in mask.items()
        if allowed
    ]


def get_mask_reasons(state, available_tools=None):
    """Explain why each masked action is unavailable."""

    mask = get_action_mask(state, available_tools)
    reasons = {}

    attempted = set(
        state.completed_actions + state.failed_actions
    )

    for action, allowed in mask.items():

        if allowed:
            continue

        if state.status in {
            "closed",
            "completed",
            "awaiting_human_review",
        }:
            reasons[action] = "Case is not active"

        elif action in attempted:
            reasons[action] = "Action already attempted"

        elif (
            available_tools is not None
            and action in EVIDENCE_ACTIONS
            and action not in available_tools
        ):
            reasons[action] = "FAA tool unavailable"

        elif action == "RECOMMEND_REPORT_GENERATION":
            reasons[action] = "No evidence retrieved yet"

        else:
            reasons[action] = "Required input unavailable"

    return reasons
