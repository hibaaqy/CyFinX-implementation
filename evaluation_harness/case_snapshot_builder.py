#!/usr/bin/env python3
"""Build case-time evidence snapshots for the CyFinX evaluation harness."""

import argparse
import csv
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_timestamp(value):
    if not value:
        return None
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def read_csv(folder, filename):
    path = Path(folder) / filename
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def rows_by(rows, column):
    grouped = {}
    for row in rows:
        grouped.setdefault(row.get(column, ""), []).append(row)
    return grouped


def before_or_at(row, column, cutoff):
    timestamp = parse_timestamp(row.get(column))
    return timestamp is not None and timestamp <= cutoff


def safe_row(row, allowed_columns):
    return {column: row[column] for column in allowed_columns if row.get(column, "") != ""}


def reconstruct_device_last_seen(device_id, sessions, customer_links, cutoff):
    session_ends = [
        parse_timestamp(row["Session_end"])
        for row in sessions
        if row.get("Device_ID") == device_id
        and parse_timestamp(row.get("Session_start")) <= cutoff
        and parse_timestamp(row.get("Session_end")) is not None
        and parse_timestamp(row["Session_end"]) <= cutoff
    ]
    if session_ends:
        return max(session_ends).strftime(TIMESTAMP_FORMAT)

    session_starts = [
        parse_timestamp(row["Session_start"])
        for row in sessions
        if row.get("Device_ID") == device_id
        and parse_timestamp(row.get("Session_start")) <= cutoff
    ]
    if session_starts:
        return max(session_starts).strftime(TIMESTAMP_FORMAT)

    link_times = [
        parse_timestamp(row["First_seen"])
        for row in customer_links
        if row.get("Device_ID") == device_id
        and parse_timestamp(row.get("First_seen")) is not None
        and parse_timestamp(row["First_seen"]) <= cutoff
    ]
    if link_times:
        return max(link_times).strftime(TIMESTAMP_FORMAT)
    return None


def build_snapshot(case, dataset_folder):
    customer_id = case["Customer_ID"]
    cutoff = parse_timestamp(case["Case_created_timestamp"])

    customers = read_csv(dataset_folder, "customers.csv")
    devices = read_csv(dataset_folder, "Devices.csv")
    customer_devices = read_csv(dataset_folder, "Customer_Device.csv")
    beneficiaries = read_csv(dataset_folder, "Beneficiaries.csv")
    sessions = read_csv(dataset_folder, "Network_Sessions.csv")
    auth_logs = read_csv(dataset_folder, "Authentication_Logs.csv")
    transactions = read_csv(dataset_folder, "Transactions.csv")
    biometric_logs = read_csv(dataset_folder, "Biometric_Logs.csv")
    complaints = read_csv(dataset_folder, "Complaints.csv")
    alerts = read_csv(dataset_folder, "Fraud_Alerts.csv")
    kyc_records = read_csv(dataset_folder, "KYC_records.csv")
    agents = read_csv(dataset_folder, "Agent_Retailers.csv")

    customer_by_id = {row["Customer_ID"]: row for row in customers}
    customer = customer_by_id.get(customer_id, {})

    available_sessions = [
        row for row in sessions
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Session_start", cutoff)
    ]

    available_device_links = [
        row for row in customer_devices
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "First_seen", cutoff)
    ]
    linked_device_ids = {row["Device_ID"] for row in available_device_links}
    linked_device_ids.update(row["Device_ID"] for row in available_sessions)
    devices_by_id = {row["Device_ID"]: row for row in devices}

    rebuilt_devices = []
    for device_id in sorted(linked_device_ids):
        device = devices_by_id.get(device_id)
        if not device:
            continue
        first_seen = parse_timestamp(device.get("Device_first_seen"))
        if first_seen is not None and first_seen > cutoff:
            continue
        rebuilt = safe_row(device, (
            "Device_ID", "Device_type", "Device_OS", "Device_model",
            "Device_first_seen", "Device_status",
        ))
        last_seen = reconstruct_device_last_seen(
            device_id, available_sessions, available_device_links, cutoff
        )
        if last_seen:
            rebuilt["Last_seen"] = last_seen
        rebuilt_devices.append(rebuilt)

    available_auth = [
        safe_row(row, (
            "Auth_event_ID", "Customer_ID", "Device_ID", "Session_ID",
            "Event_timestamp", "Event_type", "Auth_method", "Result",
            "Failure_reason", "Attempt_count",
        ))
        for row in auth_logs
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Event_timestamp", cutoff)
    ]

    available_transactions = [
        safe_row(row, (
            "Transaction_ID", "Customer_ID", "Session_ID", "Beneficiary_ID",
            "Agent_ID", "Receiver_ID", "Timestamp", "Transaction_Type",
            "Amount", "Currency", "Channel", "Transaction_status",
            "Sender_balance_before", "Sender_balance_after",
        ))
        for row in transactions
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Timestamp", cutoff)
    ]

    available_biometrics = [
        safe_row(row, (
            "Biometric_event_ID", "Customer_ID", "Transaction_ID", "Agent_ID",
            "Event_Timestamp", "Biometric_type", "Biometric_required",
            "Attempt_count", "Failed_attempts", "Result",
        ))
        for row in biometric_logs
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Event_Timestamp", cutoff)
    ]

    available_beneficiaries = [
        safe_row(row, (
            "Beneficiary_ID", "Customer_ID", "Beneficiary_customer_ID",
            "Beneficiary_account", "Beneficiary_type",
            "Beneficiary_added_time", "Beneficiary_status",
        ))
        for row in beneficiaries
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Beneficiary_added_time", cutoff)
    ]

    available_complaints = [
        safe_row(row, (
            "Complaint_ID", "Customer_ID", "Transaction_ID",
            "Complaint_timestamp", "Complaint_Type", "Complaint_channel",
            "Complaint_description", "Complaint_status",
        ))
        for row in complaints
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Complaint_timestamp", cutoff)
    ]

    available_alerts = [
        safe_row(row, (
            "Alert_ID", "Customer_ID", "Transaction_ID", "Alert_timestamp",
            "Alert_type", "Criticality_score", "Criticality_level",
            "Alert_source", "Alert_status",
        ))
        for row in alerts
        if row["Customer_ID"] == customer_id
        and before_or_at(row, "Alert_timestamp", cutoff)
    ]

    available_kyc = []
    for row in kyc_records:
        if row["Customer_ID"] != customer_id:
            continue
        registered = parse_timestamp(row.get("KYC_Reg_Date"))
        if registered is None or registered > cutoff:
            continue
        rebuilt = safe_row(row, (
            "KYC_ID", "Customer_ID", "Reg_Mobile", "City",
            "KYC_Reg_Date", "KYC_status",
        ))
        rebuilt.pop("Reg_Mobile", None)
        rebuilt.pop("Customer_ID", None)
        updated = parse_timestamp(row.get("KYC_last_updated_date"))
        if updated is not None and updated <= cutoff:
            rebuilt["KYC_last_updated_date"] = row["KYC_last_updated_date"]
        available_kyc.append(rebuilt)

    available_sessions_output = []
    for row in available_sessions:
        rebuilt = safe_row(row, (
            "Session_ID", "Customer_ID", "Device_ID", "Session_start",
            "City", "Network_type", "ISP",
        ))
        rebuilt.pop("Customer_ID", None)
        session_end = parse_timestamp(row.get("Session_end"))
        if session_end is not None and session_end <= cutoff:
            rebuilt["Session_end"] = row["Session_end"]
        available_sessions_output.append(rebuilt)

    customer_output = safe_row(customer, (
        "Customer_ID", "Reg_Date", "Acc_Status", "City", "Customer_segment",
    ))

    case_alert = next(
        (row for row in available_alerts if row["Alert_ID"] == case.get("Alert_ID")),
        None,
    )
    case_complaint = next(
        (row for row in available_complaints if row["Complaint_ID"] == case.get("Complaint_ID")),
        None,
    )

    transaction_ids = set()
    if case_alert:
        transaction_ids.add(case_alert.get("Transaction_ID"))
    if case_complaint:
        transaction_ids.add(case_complaint.get("Transaction_ID"))
    primary_transactions = [
        row for row in available_transactions
        if row["Transaction_ID"] in transaction_ids
    ]

    agent_ids = {
        row.get("Agent_ID")
        for row in available_transactions + available_biometrics
        if row.get("Agent_ID")
    }
    agents_by_id = {row["Agent_ID"]: row for row in agents}
    available_agents = [
        safe_row(agents_by_id[agent_id], (
            "Agent_ID", "Agent_location", "City", "Agent_reg_date",
            "Agent_status", "Agent_type",
        ))
        for agent_id in sorted(agent_ids)
        if agent_id in agents_by_id
        and (
            parse_timestamp(agents_by_id[agent_id].get("Agent_reg_date")) is None
            or parse_timestamp(agents_by_id[agent_id].get("Agent_reg_date")) <= cutoff
        )
    ]
    for agent in available_agents:
        agent.pop("Agent_location", None)

    return {
        "snapshot_version": "1.0",
        "case": safe_row(case, (
            "Case_ID", "Customer_ID", "Alert_ID", "Complaint_ID",
            "Case_created_timestamp", "Case_source", "Case_status",
            "Case_priority",
        )),
        "case_time_cutoff": case["Case_created_timestamp"],
        "customer": customer_output,
        "origin": {
            "alert": case_alert,
            "complaint": case_complaint,
        },
        "primary_transactions": primary_transactions,
        "evidence": {
            "transactions": available_transactions,
            "authentication_logs": available_auth,
            "biometric_logs": available_biometrics,
            "network_sessions": available_sessions_output,
            "beneficiaries": available_beneficiaries,
            "devices": rebuilt_devices,
            "customer_device_links": [
                safe_row(row, (
                    "Customer_Device_ID", "Customer_ID", "Device_ID",
                    "First_seen", "Link_status",
                ))
                for row in available_device_links
            ],
            "kyc_records": available_kyc,
            "complaints": available_complaints,
            "alerts": available_alerts,
            "agents": available_agents,
        },
    }


def find_timestamp_fields(value, cutoff, path=""):
    errors = []
    timestamp_columns = (
        "_timestamp", "_Timestamp", "_time", "_time", "Timestamp",
        "Session_start", "Session_end", "Event_timestamp", "Event_Timestamp",
        "Beneficiary_added_time", "KYC_Reg_Date", "KYC_last_updated_date",
        "First_seen", "Last_seen", "Device_first_seen", "Reg_Date",
        "Alert_timestamp", "Complaint_timestamp", "Case_created_timestamp",
        "Agent_reg_date",
    )
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in timestamp_columns:
                timestamp = parse_timestamp(child)
                if timestamp is not None and timestamp > cutoff:
                    errors.append(f"{child_path}={child}")
            errors.extend(find_timestamp_fields(child, cutoff, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            errors.extend(find_timestamp_fields(child, cutoff, f"{path}[{index}]"))
    return errors


def validate_snapshot(snapshot, ground_truth_rows):
    cutoff = parse_timestamp(snapshot["case_time_cutoff"])
    errors = find_timestamp_fields(snapshot, cutoff)

    serialized = json.dumps(snapshot, ensure_ascii=False)
    for row in ground_truth_rows:
        forbidden_values = (
            row.get("Fraud_type", ""),
            row.get("Scenario_ID", ""),
            row.get("Validation_notes", ""),
        )
        for forbidden in forbidden_values:
            if forbidden and forbidden in serialized:
                errors.append(
                    f"ground-truth value leaked: {forbidden[:80]}"
                )

    customer_id = snapshot["case"]["Customer_ID"]
    evidence = snapshot["evidence"]
    for evidence_key in (
        "transactions", "authentication_logs", "biometric_logs",
        "network_sessions", "beneficiaries", "kyc_records",
        "complaints", "alerts",
    ):
        for row in evidence[evidence_key]:
            if row.get("Customer_ID") and row["Customer_ID"] != customer_id:
                errors.append(
                    f"{evidence_key} contains another customer: "
                    f"{row['Customer_ID']}"
                )

    if snapshot["origin"]["alert"] is not None:
        alert_id = snapshot["case"].get("Alert_ID")
        if snapshot["origin"]["alert"].get("Alert_ID") != alert_id:
            errors.append("origin alert does not match case")
    if snapshot["origin"]["complaint"] is not None:
        complaint_id = snapshot["case"].get("Complaint_ID")
        if snapshot["origin"]["complaint"].get("Complaint_ID") != complaint_id:
            errors.append("origin complaint does not match case")

    return errors


def build_all(dataset_folder, output_folder):
    dataset_folder = Path(dataset_folder)
    output_folder = Path(output_folder)
    snapshots_folder = output_folder / "snapshots"
    ground_truth_folder = output_folder / "ground_truth"
    snapshots_folder.mkdir(parents=True, exist_ok=True)
    ground_truth_folder.mkdir(parents=True, exist_ok=True)

    ground_truth_source = dataset_folder / "Ground_Truth.csv"
    shutil.copy2(ground_truth_source, ground_truth_folder / "Ground_Truth.csv")
    ground_truth_rows = read_csv(dataset_folder, "Ground_Truth.csv")

    cases = read_csv(dataset_folder, "Cases.csv")
    all_errors = []
    alert_count = 0
    complaint_count = 0

    for case in cases:
        snapshot = build_snapshot(case, dataset_folder)
        snapshot_errors = validate_snapshot(snapshot, ground_truth_rows)
        if snapshot_errors:
            all_errors.append((case["Case_ID"], snapshot_errors))

        snapshot_path = snapshots_folder / f"{case['Case_ID']}.json"
        snapshot_path.write_text(
            json.dumps(snapshot, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if case["Case_source"] == "alert":
            alert_count += 1
        elif case["Case_source"] == "complaint":
            complaint_count += 1

    manifest = {
        "dataset": str(dataset_folder),
        "case_count": len(cases),
        "snapshot_count": len(cases),
        "alert_originated_cases": alert_count,
        "complaint_originated_cases": complaint_count,
        "validation_errors": [
            {"case_id": case_id, "errors": errors}
            for case_id, errors in all_errors
        ],
        "ground_truth_file": str(
            ground_truth_folder / "Ground_Truth.csv"
        ),
    }
    (output_folder / "snapshot_manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest


def validate_existing(output_folder):
    output_folder = Path(output_folder)
    ground_truth_rows = read_csv(output_folder / "ground_truth", "Ground_Truth.csv")
    manifest_errors = []
    snapshot_count = 0

    for snapshot_path in sorted((output_folder / "snapshots").glob("*.json")):
        snapshot_count += 1
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
        snapshot_errors = validate_snapshot(snapshot, ground_truth_rows)
        if snapshot_errors:
            manifest_errors.append({
                "case_id": snapshot["case"]["Case_ID"],
                "errors": snapshot_errors,
            })

    result = {
        "snapshot_count": snapshot_count,
        "validation_errors": manifest_errors,
    }
    print(json.dumps(result, indent=2))
    return result


def main():
    parser = argparse.ArgumentParser(
        description="Build case-time evidence snapshots."
    )
    parser.add_argument(
        "--dataset",
        help="Source investigation CSV folder; not required for --validate-existing.",
    )
    parser.add_argument("--output", default="evaluation_harness")
    parser.add_argument(
        "--validate-existing",
        action="store_true",
        help="Validate existing snapshots instead of rebuilding them.",
    )
    args = parser.parse_args()

    if args.validate_existing:
        result = validate_existing(args.output)
        if result["validation_errors"]:
            return 1
        return 0
    if not args.dataset:
        parser.error("--dataset is required unless --validate-existing is used")

    manifest = build_all(args.dataset, args.output)
    print(json.dumps(manifest, indent=2))
    if manifest["validation_errors"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
