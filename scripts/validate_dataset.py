
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "CyFinX_V3_Final_2500_14_CSVs"

# CSV files and their expected primary keys
TABLES = {
    "Agent_Retailers": ("Agent_Retailers.csv", "Agent_ID"),
    "Authentication_Logs": ("Authentication_Logs.csv", "Auth_event_ID"),
    "Beneficiaries": ("Beneficiaries.csv", "Beneficiary_ID"),
    "Biometric_Logs": ("Biometric_Logs.csv", "Biometric_event_ID"),
    "Cases": ("Cases.csv", "Case_ID"),
    "Complaints": ("Complaints.csv", "Complaint_ID"),
    "Customer_Device": ("Customer_Device.csv", "Customer_Device_ID"),
    "customers": ("customers.csv", "Customer_ID"),
    "Devices": ("Devices.csv", "Device_ID"),
    "Fraud_Alerts": ("Fraud_Alerts.csv", "Alert_ID"),
    "Ground_Truth": ("Ground_Truth.csv", "Case_ID"),
    "KYC_records": ("KYC_records.csv", "KYC_ID"),
    "Network_Sessions": ("Network_Sessions.csv", "Session_ID"),
    "Transactions": ("Transactions.csv", "Transaction_ID"),
}

# Candidate foreign-key relationships based on column names.
FOREIGN_KEYS = [
    ("Authentication_Logs", "Customer_ID", "customers", "Customer_ID"),
    ("Authentication_Logs", "Device_ID", "Devices", "Device_ID"),
    ("Authentication_Logs", "Session_ID", "Network_Sessions", "Session_ID"),

    ("Beneficiaries", "Customer_ID", "customers", "Customer_ID"),

    ("Biometric_Logs", "Customer_ID", "customers", "Customer_ID"),
    ("Biometric_Logs", "Transaction_ID", "Transactions", "Transaction_ID"),
    ("Biometric_Logs", "Agent_ID", "Agent_Retailers", "Agent_ID"),

    ("Cases", "Customer_ID", "customers", "Customer_ID"),
    ("Cases", "Alert_ID", "Fraud_Alerts", "Alert_ID"),
    ("Cases", "Complaint_ID", "Complaints", "Complaint_ID"),

    ("Complaints", "Customer_ID", "customers", "Customer_ID"),
    ("Complaints", "Transaction_ID", "Transactions", "Transaction_ID"),

    ("Customer_Device", "Customer_ID", "customers", "Customer_ID"),
    ("Customer_Device", "Device_ID", "Devices", "Device_ID"),

    ("Fraud_Alerts", "Customer_ID", "customers", "Customer_ID"),
    ("Fraud_Alerts", "Transaction_ID", "Transactions", "Transaction_ID"),

    ("KYC_records", "Customer_ID", "customers", "Customer_ID"),

    ("Network_Sessions", "Customer_ID", "customers", "Customer_ID"),
    ("Network_Sessions", "Device_ID", "Devices", "Device_ID"),

    ("Transactions", "Customer_ID", "customers", "Customer_ID"),
    ("Transactions", "Session_ID", "Network_Sessions", "Session_ID"),
    ("Transactions", "Beneficiary_ID", "Beneficiaries", "Beneficiary_ID"),
    ("Transactions", "Agent_ID", "Agent_Retailers", "Agent_ID"),
]

def get_key(df, column):
    if column not in df.columns:
        return None

    values = df[column].astype("string").str.strip()
    return values.mask(values.eq(""))

def main():
    print("=" * 65)
    print("CYFINX DATASET VALIDATION")
    print("=" * 65)

    if not DATA_DIR.exists():
        raise FileNotFoundError(f"Dataset folder not found: {DATA_DIR}")

    data = {}

    # Load all datasets
    for table, (filename, primary_key) in TABLES.items():
        path = DATA_DIR / filename

        if not path.exists():
            print(f"MISSING FILE: {filename}")
            continue

        data[table] = pd.read_csv(
            path,
            dtype="string",
            keep_default_na=False
        )

    print("\n1. PRIMARY KEY VALIDATION")

    for table, (_, primary_key) in TABLES.items():
        if table not in data:
            continue

        values = get_key(data[table], primary_key)

        if values is None:
            print(f"{table}: MISSING COLUMN {primary_key}")
            continue

        missing = values.isna().sum()
        duplicate_mask = values.notna() & values.duplicated(keep=False)
        duplicate_keys = values[duplicate_mask].nunique()

        print(
            f"{table}: missing={missing}, "
            f"duplicate_keys={duplicate_keys}"
        )

    print("\n2. FOREIGN KEY VALIDATION")

    for child, child_col, parent, parent_col in FOREIGN_KEYS:
        if child not in data or parent not in data:
            print(f"{child}.{child_col}: TABLE NOT FOUND")
            continue

        child_values = get_key(data[child], child_col)
        parent_values = get_key(data[parent], parent_col)

        if child_values is None or parent_values is None:
            print(f"{child}.{child_col}: COLUMN NOT FOUND")
            continue

        references = child_values.dropna()
        valid_keys = set(parent_values.dropna())

        orphan_count = (~references.isin(valid_keys)).sum()

        print(
            f"{child}.{child_col} -> {parent}.{parent_col}: "
            f"orphan_records={orphan_count}"
        )

    print("\n3. CASE SOURCE VALIDATION")

    if "Cases" in data:
        cases = data["Cases"]

        alert_ids = get_key(cases, "Alert_ID")
        complaint_ids = get_key(cases, "Complaint_ID")

        if alert_ids is not None and complaint_ids is not None:
            no_source = (
                alert_ids.isna() & complaint_ids.isna()
            ).sum()

            print(f"Cases without alert or complaint: {no_source}")

    print("\n4. GROUND TRUTH VALIDATION")

    if "Ground_Truth" in data and "Cases" in data:
        gt_ids = get_key(data["Ground_Truth"], "Case_ID")
        case_ids = get_key(data["Cases"], "Case_ID")

        if gt_ids is not None and case_ids is not None:
            unmatched = (~gt_ids.dropna().isin(set(case_ids.dropna()))).sum()

            print(f"Ground-truth cases without matching cases: {unmatched}")

    print("\n5. EXPECTED ACCOUNTS TABLE")

    if not (DATA_DIR / "Accounts.csv").exists():
        print("Accounts.csv is missing from the dataset.")
        print("Check whether this table was intentionally excluded.")

    print("\n" + "=" * 65)
    print("VALIDATION COMPLETED")
    print("=" * 65)

if __name__ == "__main__":
    main()
