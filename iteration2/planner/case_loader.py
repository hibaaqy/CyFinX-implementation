"""Create the Step 0 CyFinX case state from the actual V3 CSV dataset.

This module reads ONLY Cases.csv and the linked alert/complaint intake record.
It never reads Ground_Truth.csv or any FAA evidence tables.
"""
import csv
import io
import zipfile
from datetime import datetime
from pathlib import Path

from .state_schema import CaseState


def _read_csv(archive: zipfile.ZipFile, filename: str) -> list[dict[str, str]]:
    with archive.open(filename) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        return list(reader)


def _not_later_than(value: str, case_created: str, field_name: str) -> None:
    if value and datetime.fromisoformat(value) > datetime.fromisoformat(case_created):
        raise ValueError(f"{field_name} occurs after case creation; cannot use at Step 0")


def load_initial_case(zip_path: str | Path, case_id: str) -> CaseState:
    """Build initial state using ONLY the linked complaint or alert as of intake."""
    with zipfile.ZipFile(zip_path) as archive:
        cases = _read_csv(archive, "Cases.csv")
        row = next((r for r in cases if r["Case_ID"] == case_id), None)
        if row is None:
            raise ValueError(f"Case not found: {case_id}")

        source = row["Case_source"].strip().lower()
        created = row["Case_created_timestamp"]
        intake = {
            "case_priority": row["Case_priority"],
            "case_created_timestamp": created,
        }
        transaction_id = None

        if source == "alert":
            alert_id = row["Alert_ID"]
            if not alert_id:
                raise ValueError(f"Missing Alert_ID for {case_id}")
            alerts = _read_csv(archive, "Fraud_Alerts.csv")
            alert = next((r for r in alerts if r["Alert_ID"] == alert_id), None)
            if alert is None:
                raise ValueError(f"Missing linked alert: {alert_id}")
            if alert["Customer_ID"] != row["Customer_ID"]:
                raise ValueError("Case/alert customer mismatch")
            _not_later_than(alert["Alert_timestamp"], created, "Alert_timestamp")
            transaction_id = alert["Transaction_ID"] or None
            intake.update({
                "alert_id": alert_id,
                "alert_type": alert["Alert_type"],
                "criticality_score": alert["Criticality_score"],
                "criticality_level": alert["Criticality_level"],
                "alert_timestamp": alert["Alert_timestamp"],
                "alert_source": alert["Alert_source"],
            })
        elif source == "complaint":
            complaint_id = row["Complaint_ID"]
            if not complaint_id:
                raise ValueError(f"Missing Complaint_ID for {case_id}")
            complaints = _read_csv(archive, "Complaints.csv")
            complaint = next((r for r in complaints if r["Complaint_ID"] == complaint_id), None)
            if complaint is None:
                raise ValueError(f"Missing linked complaint: {complaint_id}")
            if complaint["Customer_ID"] != row["Customer_ID"]:
                raise ValueError("Case/complaint customer mismatch")
            _not_later_than(complaint["Complaint_timestamp"], created, "Complaint_timestamp")
            transaction_id = complaint["Transaction_ID"] or None
            intake.update({
                "complaint_id": complaint_id,
                "complaint_type": complaint["Complaint_Type"],
                "complaint_channel": complaint["Complaint_channel"],
                "complaint_description": complaint["Complaint_description"],
                "complaint_timestamp": complaint["Complaint_timestamp"],
            })
        else:
            raise ValueError(f"Unexpected Case_source: {source}")

    return CaseState(
        case_id=row["Case_ID"],
        case_source=source,
        customer_id=row["Customer_ID"],
        transaction_id=transaction_id,
        intake_data=intake,
    )
