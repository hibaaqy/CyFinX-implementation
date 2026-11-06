
from dataclasses import dataclass, field
from typing import Any

from .actions import EVIDENCE_ACTIONS


@dataclass
class CaseState:
    case_id: str
    case_source: str

    # Identifiers available at case creation
    customer_id: str | None = None
    transaction_id: str | None = None

    # Only information supplied by the initial alert/complaint
    intake_data: dict[str, Any] = field(default_factory=dict)

    # Evidence discovered by FAA during investigation
    evidence: dict[str, Any] = field(default_factory=dict)

    completed_actions: list[str] = field(default_factory=list)
    failed_actions: list[str] = field(default_factory=list)

    step_count: int = 0
    status: str = "new"

    def available_actions(self) -> list[str]:
        """Evidence actions that have not already been attempted."""
        attempted = set(
            self.completed_actions + self.failed_actions
        )

        return [
            action
            for action in EVIDENCE_ACTIONS
            if action not in attempted
        ]

    def update_after_action(
        self,
        action: str,
        evidence_result: dict[str, Any],
        success: bool = True,
    ) -> None:
        """Update state after FAA executes an evidence action."""

        if action not in EVIDENCE_ACTIONS:
            raise ValueError(f"Unknown evidence action: {action}")

        if (
            action in self.completed_actions
            or action in self.failed_actions
        ):
            raise ValueError(f"Action already attempted: {action}")

        if success:
            self.completed_actions.append(action)
            self.evidence[action] = evidence_result
        else:
            self.failed_actions.append(action)

        self.step_count += 1
        self.status = "investigating"

    def to_dict(self) -> dict[str, Any]:
        """Convert the state to a serializable dictionary."""
        from dataclasses import asdict
        return asdict(self)
