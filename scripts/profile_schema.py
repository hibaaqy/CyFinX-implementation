
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "CyFinX_V3_Final_2500_14_CSVs"

DATE_HINTS = (
    "date", "timestamp", "time", "dob",
    "first_seen", "last_seen", "_start", "_end"
)

NUMERIC_HINTS = (
    "amount", "balance", "score", "latitude",
    "longitude", "attempt_count", "failed_attempts",
    "is_fraud"
)


def parse_date_rate(series):
    try:
        parsed = pd.to_datetime(
            series, errors="coerce", format="mixed"
        )
    except (TypeError, ValueError):
        parsed = pd.to_datetime(series, errors="coerce")

    return parsed.notna().sum()


def check_relationship(data, child, child_col, parent, parent_col):
    child_values = data[child][child_col].str.strip()
    parent_values = set(
        data[parent][parent_col]
        .str.strip()
        .loc[lambda x: x.ne("")]
    )

    active = child_values[child_values.ne("")]
    unmatched = (~active.isin(parent_values)).sum()

    print(
        f"{child}.{child_col} -> {parent}.{parent_col}: "
        f"nonblank={len(active)}, unmatched={unmatched}"
    )


def main():
    files = list(DATA_DIR.glob("*.csv"))

    data = {
        file.stem: pd.read_csv(
            file, dtype="string", keep_default_na=False
        )
        for file in files
    }

    print("=== DATA TYPE PROFILE ===")

    for table, df in data.items():
        print(f"\n{table} ({len(df)} rows)")

        for column in df.columns:
            values = df[column].str.strip()
            nonblank = values[values.ne("")]

            name = column.lower()

            if any(hint in name for hint in DATE_HINTS):
                parsed = parse_date_rate(nonblank)
                print(
                    f"  {column}: DATETIME candidate; "
                    f"parseable={parsed}/{len(nonblank)}"
                )

            elif any(hint in name for hint in NUMERIC_HINTS):
                parsed = pd.to_numeric(
                    nonblank, errors="coerce"
                ).notna().sum()

                print(
                    f"  {column}: NUMERIC candidate; "
                    f"parseable={parsed}/{len(nonblank)}"
                )

    print("\n=== UNCONFIRMED RELATIONSHIPS ===")

    check_relationship(
        data, "Beneficiaries", "Beneficiary_customer_ID",
        "customers", "Customer_ID"
    )

    check_relationship(
        data, "Transactions", "Receiver_ID",
        "customers", "Customer_ID"
    )

    check_relationship(
        data, "Transactions", "Receiver_ID",
        "Beneficiaries", "Beneficiary_ID"
    )

    check_relationship(
        data, "Transactions", "Receiver_ID",
        "Beneficiaries", "Beneficiary_customer_ID"
    )

    print("\n=== CASE CUSTOMER CONSISTENCY ===")

    cases = data["Cases"]

    for ref_col, source_table, source_key in [
        ("Alert_ID", "Fraud_Alerts", "Alert_ID"),
        ("Complaint_ID", "Complaints", "Complaint_ID")
    ]:
        selected = cases[
            cases[ref_col].str.strip().ne("")
        ]

        merged = selected.merge(
            data[source_table][[source_key, "Customer_ID"]],
            left_on=ref_col,
            right_on=source_key,
            suffixes=("_case", "_source")
        )

        mismatches = (
            merged["Customer_ID_case"]
            != merged["Customer_ID_source"]
        ).sum()

        print(f"{ref_col}: customer mismatches={mismatches}")

    print("\nPROFILE COMPLETED")


if __name__ == "__main__":
    main()
