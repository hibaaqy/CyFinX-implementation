
from pathlib import Path
import sys
import csv
from decimal import Decimal
from datetime import timezone

import pandas as pd

# Make the project root available for imports
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import (
    Date,
    DateTime,
    String,
    Numeric,
    Integer,
    Float,
    select,
    func,
)

from app.database.connection import engine, OPERATIONAL_DB_PATH
from app.database.models import (
    Base,
    Customers,
    AgentRetailers,
    Devices,
    NetworkSessions,
    Beneficiaries,
    Transactions,
    AuthenticationLogs,
    BiometricLogs,
    FraudAlerts,
    Complaints,
    Cases,
    CustomerDevice,
    KYCRecords,
)


DATA_DIR = ROOT / "CyFinX_V3_Final_2500_14_CSVs"
BATCH_SIZE = 1000

# Parent tables must be loaded before tables that reference them.
IMPORT_ORDER = [
    (Customers, "customers.csv"),
    (AgentRetailers, "Agent_Retailers.csv"),
    (Devices, "Devices.csv"),
    (NetworkSessions, "Network_Sessions.csv"),
    (Beneficiaries, "Beneficiaries.csv"),
    (Transactions, "Transactions.csv"),
    (AuthenticationLogs, "Authentication_Logs.csv"),
    (BiometricLogs, "Biometric_Logs.csv"),
    (FraudAlerts, "Fraud_Alerts.csv"),
    (Complaints, "Complaints.csv"),
    (Cases, "Cases.csv"),
    (CustomerDevice, "Customer_Device.csv"),
    (KYCRecords, "KYC_records.csv"),
]


def convert_value(raw_value, column):
    """Convert a CSV value according to its SQLAlchemy column type."""

    value = raw_value.strip()

    if value == "":
        if not column.nullable:
            raise ValueError(
                f"Empty value in required column: {column.name}"
            )
        return None

    column_type = column.type

    if isinstance(column_type, DateTime):
        parsed = pd.to_datetime(value, errors="raise")
        result = parsed.to_pydatetime()

        # Normalize timezone-aware values to UTC without timezone info.
        if result.tzinfo is not None:
            result = result.astimezone(timezone.utc).replace(tzinfo=None)

        return result

    if isinstance(column_type, Date):
        return pd.to_datetime(value, errors="raise").date()

    if isinstance(column_type, Numeric):
        return Decimal(value)

    if isinstance(column_type, Integer):
        number = Decimal(value)

        if number != number.to_integral_value():
            raise ValueError(
                f"Non-integer value in {column.name}: {value}"
            )

        return int(number)

    if isinstance(column_type, Float):
        return float(value)

    if isinstance(column_type, String):
        return value

    return value


def import_table(connection, model, filename):
    """Import one CSV file into its corresponding SQLAlchemy table."""

    file_path = DATA_DIR / filename

    if not file_path.exists():
        raise FileNotFoundError(f"Missing CSV file: {file_path}")

    table = model.__table__
    columns = {column.name: column for column in table.columns}

    inserted = 0
    batch = []

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as csv_file:

        reader = csv.DictReader(csv_file)

        if reader.fieldnames is None:
            raise ValueError(f"No CSV headers found: {filename}")

        missing = set(columns) - set(reader.fieldnames)
        extra = set(reader.fieldnames) - set(columns)

        if missing:
            raise ValueError(
                f"{filename} is missing columns: {sorted(missing)}"
            )

        if extra:
            raise ValueError(
                f"{filename} has unexpected columns: {sorted(extra)}"
            )

        for line_number, row in enumerate(reader, start=2):
            try:
                converted = {
                    name: convert_value(row[name], column)
                    for name, column in columns.items()
                }

                batch.append(converted)

            except Exception as error:
                raise ValueError(
                    f"Error in {filename}, line {line_number}: {error}"
                ) from error

            if len(batch) >= BATCH_SIZE:
                connection.execute(table.insert(), batch)
                inserted += len(batch)
                batch.clear()

        if batch:
            connection.execute(table.insert(), batch)
            inserted += len(batch)

    return inserted


def main():

    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Dataset directory not found: {DATA_DIR}"
        )

    if not OPERATIONAL_DB_PATH.exists():
        raise FileNotFoundError(
            "Operational database does not exist. "
            "Run create_database.py first."
        )

    print("=" * 65)
    print("CYFINX OPERATIONAL DATA IMPORT")
    print("=" * 65)

    imported_counts = {}

    # All imports happen in one transaction.
    # An error rolls back the entire import.
    with engine.begin() as connection:

        foreign_keys = connection.exec_driver_sql(
            "PRAGMA foreign_keys"
        ).scalar_one()

        if foreign_keys != 1:
            raise RuntimeError(
                "SQLite foreign-key enforcement is not enabled."
            )

        # Prevent accidental duplicate imports.
        for model, filename in IMPORT_ORDER:
            count = connection.execute(
                select(func.count()).select_from(model.__table__)
            ).scalar_one()

            if count > 0:
                raise RuntimeError(
                    f"Table {model.__tablename__} already contains "
                    f"{count} records. Import cancelled to prevent "
                    "duplicate data."
                )

        print("\nImporting CSV files...\n")

        for model, filename in IMPORT_ORDER:

            count = import_table(
                connection,
                model,
                filename
            )

            imported_counts[model.__tablename__] = count

            print(
                f"{model.__tablename__}: "
                f"{count:,} records imported"
            )

        # Verify all foreign-key relationships.
        violations = connection.exec_driver_sql(
            "PRAGMA foreign_key_check"
        ).fetchall()

        if violations:
            raise RuntimeError(
                f"Foreign-key violations found: {violations[:10]}"
            )

        print("\nForeign-key validation passed.")

    print("\n=== FINAL DATABASE VERIFICATION ===")

    with engine.connect() as connection:

        total_records = 0

        for model, filename in IMPORT_ORDER:

            count = connection.execute(
                select(func.count()).select_from(model.__table__)
            ).scalar_one()

            total_records += count

            print(f"{model.__tablename__}: {count:,} records")

            if count != imported_counts[model.__tablename__]:
                raise RuntimeError(
                    f"Record count mismatch in {model.__tablename__}"
                )

    print("\n" + "=" * 65)
    print("OPERATIONAL DATA IMPORT SUCCESSFUL")
    print(f"Total records imported: {total_records:,}")
    print(f"Database: {OPERATIONAL_DB_PATH}")
    print("=" * 65)


if __name__ == "__main__":
    main()
