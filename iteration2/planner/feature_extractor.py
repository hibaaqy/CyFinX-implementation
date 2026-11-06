#It will convert the case state into features your ML model can use
#it converts the data into the numerical values that the model can use

from .actions import EVIDENCE_ACTIONS
from .state_schema import CaseState


def _get(record, *names):
    """Read a field without depending on capitalization."""
    if not isinstance(record, dict):
        return None

    lookup = {str(k).lower(): v for k, v in record.items()}

    for name in names:
        value = lookup.get(name.lower())
        if value is not None and value != "":
            return value

    return None


def _number(value):
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def _boolean(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return int(value)
    if str(value).lower() in {"true", "yes", "1"}:
        return 1
    if str(value).lower() in {"false", "no", "0"}:
        return 0
    return None


def _records(payload):
    """
    Supports:
      {"Amount": 50000}
      [{"Amount": 50000}, {"Amount": 3000}]
      {"records": [...]}
      {"rows": [...]}
    """
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]

    if isinstance(payload, dict):
        for key in ("records", "rows"):
            if isinstance(payload.get(key), list):
                return _records(payload[key])
        return [payload] if payload else []

    return []


def _count(payload, records, *names):
    explicit = _integer(_get(payload, *names))
    return explicit if explicit is not None else len(records)


def _sum_field(records, field):
    return sum(_number(_get(row, field)) or 0 for row in records)


def _first_value(payload, records, *names):
    value = _get(payload, *names)
    if value is not None:
        return value

    for record in records:
        value = _get(record, *names)
        if value is not None:
            return value

    return None


# Fixed feature names for consistent ML training.
EVIDENCE_DEFAULTS = {
    "transaction_amount": None,
    "transaction_type": None,
    "transaction_channel": None,
    "transaction_status": None,
    "transaction_has_agent": None,

    "velocity_transaction_count": None,
    "velocity_total_amount": None,

    "device_count": None,
    "inactive_device_count": None,
    "new_device_detected": None,

    "failed_authentication_events": None,
    "authentication_attempt_count": None,

    "beneficiary_count": None,
    "new_beneficiary_detected": None,

    "kyc_status": None,

    "biometric_failed_attempts": None,
    "biometric_event_count": None,

    "network_session_count": None,
    "distinct_ip_count": None,

    "customer_complaint_count": None,

    "fraud_alert_count": None,
    "maximum_alert_criticality": None,

    "retailer_status": None,
    "retailer_type": None,

    "customer_account_status": None,
    "customer_segment": None,
}


def extract_features(state: CaseState) -> dict:
    """Extract only information available at the current step."""

    intake = state.intake_data
    completed = set(state.completed_actions)
    failed = set(state.failed_actions)

    features = {
        "case_source": state.case_source,
        "case_priority": intake.get("case_priority"),
        "alert_type": intake.get("alert_type"),
        "alert_criticality_level": intake.get("criticality_level"),
        "alert_criticality_score": _number(
            intake.get("criticality_score")
        ),
        "complaint_type": intake.get("complaint_type"),
        "complaint_channel": intake.get("complaint_channel"),
        "has_transaction_id": int(bool(state.transaction_id)),
        "has_customer_id": int(bool(state.customer_id)),
        "step_count": state.step_count,
        "completed_action_count": len(completed),
        "failed_action_count": len(failed),
    }

    features.update(EVIDENCE_DEFAULTS)

    for action in EVIDENCE_ACTIONS:
        features[f"done_{action}"] = int(action in completed)
        features[f"failed_{action}"] = int(action in failed)

        # An action is observed only when FAA successfully
        # retrieved and stored its evidence.
        features[f"observed_{action}"] = int(
            action in completed and action in state.evidence
        )

    for action in EVIDENCE_ACTIONS:

        if action not in completed:
            continue

        if action not in state.evidence:
            continue

        payload = state.evidence[action]
        rows = _records(payload)

        if action == "GET_TRANSACTION_DETAILS":
            features["transaction_amount"] = _number(
                _first_value(payload, rows, "Amount", "amount")
            )
            features["transaction_type"] = _first_value(
                payload, rows, "Transaction_Type", "transaction_type"
            )
            features["transaction_channel"] = _first_value(
                payload, rows, "Channel", "channel"
            )
            features["transaction_status"] = _first_value(
                payload, rows, "Transaction_status"
            )

            agent_id = _first_value(payload, rows, "Agent_ID")
            features["transaction_has_agent"] = int(
                bool(agent_id)
            )

        elif action == "CHECK_TRANSACTION_VELOCITY":
            features["velocity_transaction_count"] = _count(
                payload, rows, "transaction_count"
            )

            total = _number(_get(payload, "total_amount"))
            features["velocity_total_amount"] = (
                total if total is not None
                else _sum_field(rows, "Amount")
            )

        elif action == "CHECK_DEVICE_HISTORY":
            features["device_count"] = _count(
                payload, rows, "device_count"
            )

            inactive = _integer(
                _get(payload, "inactive_device_count")
            )
            if inactive is None:
                inactive = sum(
                    str(_get(r, "Device_status") or "").lower()
                    == "inactive"
                    for r in rows
                )

            features["inactive_device_count"] = inactive
            features["new_device_detected"] = _boolean(
                _get(payload, "new_device_detected")
            )

        elif action == "CHECK_AUTHENTICATION_LOGS":
            failed_events = _integer(
                _get(payload, "failed_authentication_events")
            )

            if failed_events is None:
                failed_events = sum(
                    str(_get(r, "Result") or "").lower()
                    == "failed"
                    for r in rows
                )

            features["failed_authentication_events"] = failed_events

            attempts = _integer(
                _get(payload, "authentication_attempt_count")
            )

            features["authentication_attempt_count"] = (
                attempts if attempts is not None
                else int(_sum_field(rows, "Attempt_count"))
            )

        elif action == "CHECK_BENEFICIARY_HISTORY":
            features["beneficiary_count"] = _count(
                payload, rows, "beneficiary_count"
            )
            features["new_beneficiary_detected"] = _boolean(
                _get(payload, "new_beneficiary_detected")
            )

        elif action == "CHECK_KYC_RECORDS":
            features["kyc_status"] = _first_value(
                payload, rows, "KYC_status"
            )

        elif action == "CHECK_BIOMETRIC_LOGS":
            features["biometric_event_count"] = _count(
                payload, rows, "biometric_event_count"
            )

            failures = _integer(
                _get(payload, "biometric_failed_attempts")
            )

            features["biometric_failed_attempts"] = (
                failures if failures is not None
                else int(_sum_field(rows, "Failed_attempts"))
            )

        elif action == "CHECK_NETWORK_SESSIONS":
            features["network_session_count"] = _count(
                payload, rows, "network_session_count"
            )

            ip_count = _integer(
                _get(payload, "distinct_ip_count")
            )

            if ip_count is None:
                ips = {
                    _get(r, "IP_address")
                    for r in rows
                    if _get(r, "IP_address")
                }
                ip_count = len(ips)

            features["distinct_ip_count"] = ip_count

        elif action == "CHECK_CUSTOMER_COMPLAINTS":
            features["customer_complaint_count"] = _count(
                payload, rows, "complaint_count"
            )

        elif action == "CHECK_FRAUD_ALERTS":
            features["fraud_alert_count"] = _count(
                payload, rows, "alert_count"
            )

            scores = [
                _number(_get(r, "Criticality_score"))
                for r in rows
            ]
            scores = [s for s in scores if s is not None]

            explicit = _number(
                _get(payload, "maximum_alert_criticality")
            )
            features["maximum_alert_criticality"] = (
                explicit if explicit is not None
                else max(scores, default=None)
            )

        elif action == "CHECK_RETAILER_ACTIVITY":
            features["retailer_status"] = _first_value(
                payload, rows, "Agent_status"
            )
            features["retailer_type"] = _first_value(
                payload, rows, "Agent_type"
            )

        elif action == "CHECK_CUSTOMER_PROFILE":
            features["customer_account_status"] = _first_value(
                payload, rows, "Acc_Status"
            )
            features["customer_segment"] = _first_value(
                payload, rows, "Customer_segment"
            )

    return features
