
from pathlib import Path
import sqlite3

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "data" / "database" / "cyfinx_operational_staging.db"

# Candidate relationships to inspect.
RELATIONSHIPS = {
    "Authentication_Logs": [
        "Customer_ID", "Device_ID", "Session_ID"
    ],
    "Beneficiaries": [
        "Customer_ID", "Beneficiary_customer_ID"
    ],
    "Biometric_Logs": [
        "Customer_ID", "Transaction_ID", "Agent_ID"
    ],
    "Cases": [
        "Customer_ID", "Alert_ID", "Complaint_ID"
    ],
    "Complaints": [
        "Customer_ID", "Transaction_ID"
    ],
    "Customer_Device": [
        "Customer_ID", "Device_ID"
    ],
    "Fraud_Alerts": [
        "Customer_ID", "Transaction_ID"
    ],
    "KYC_records": [
        "Customer_ID"
    ],
    "Network_Sessions": [
        "Customer_ID", "Device_ID"
    ],
    "Transactions": [
        "Customer_ID", "Session_ID",
        "Beneficiary_ID", "Agent_ID", "Receiver_ID"
    ]
}

def main():
    if not DB_PATH.exists():
        raise FileNotFoundError(DB_PATH)

    with sqlite3.connect(DB_PATH) as conn:
        print("CYFINX RELATIONSHIP FIELD INSPECTION")

        for table, columns in RELATIONSHIPS.items():
            print(f"\n--- {table} ---")

            existing = {
                row[1]
                for row in conn.execute(
                    f'PRAGMA table_info("{table}")'
                )
            }

            for column in columns:
                if column not in existing:
                    print(f"{column}: COLUMN NOT FOUND")
                    continue

                query = f'''
                    SELECT
                        COUNT(*) AS total,
                        SUM(
                            CASE
                                WHEN TRIM("{column}") = ''
                                THEN 1 ELSE 0
                            END
                        ) AS blank_count,
                        COUNT(
                            DISTINCT NULLIF(TRIM("{column}"), '')
                        ) AS distinct_values
                    FROM "{table}"
                '''

                total, blanks, distinct = conn.execute(
                    query
                ).fetchone()

                print(
                    f"{column}: total={total}, "
                    f"blank={blanks}, "
                    f"distinct={distinct}"
                )

        print("\n--- CASE SOURCE DISTRIBUTION ---")

        rows = conn.execute("""
            SELECT Case_source, COUNT(*)
            FROM Cases
            GROUP BY Case_source
        """).fetchall()

        for source, count in rows:
            print(f"{source or '(blank)'}: {count}")

        print("\nINSPECTION COMPLETED")

if __name__ == "__main__":
    main()
