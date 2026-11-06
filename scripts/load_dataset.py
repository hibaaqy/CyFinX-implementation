
from pathlib import Path
import sqlite3
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]

DATA_DIR = ROOT / "CyFinX_V3_Final_2500_14_CSVs"
DB_DIR = ROOT / "data" / "database"

OPERATIONAL_DB = DB_DIR / "cyfinx_operational_staging.db"
EVALUATION_DB = DB_DIR / "cyfinx_evaluation.db"


def load_csv_files(files, database_path):
    """Load CSV files into SQLite staging tables."""

    with sqlite3.connect(database_path) as connection:

        for file in files:
            df = pd.read_csv(
                file,
                dtype=str,
                keep_default_na=False
            )

            table_name = file.stem

            df.to_sql(
                table_name,
                connection,
                if_exists="replace",
                index=False
            )

            print(
                f"Loaded {table_name}: "
                f"{len(df)} records"
            )


def main():

    if not DATA_DIR.exists():
        raise FileNotFoundError(
            f"Dataset folder not found: {DATA_DIR}"
        )

    DB_DIR.mkdir(parents=True, exist_ok=True)

    csv_files = list(DATA_DIR.glob("*.csv"))

    operational_files = [
        file for file in csv_files
        if file.name.lower() != "ground_truth.csv"
    ]

    ground_truth_files = [
        file for file in csv_files
        if file.name.lower() == "ground_truth.csv"
    ]

    if len(ground_truth_files) != 1:
        raise ValueError(
            "Expected exactly one Ground_Truth.csv file."
        )

    print("\n=== LOADING OPERATIONAL DATA ===")

    load_csv_files(
        operational_files,
        OPERATIONAL_DB
    )

    print("\n=== LOADING EVALUATION DATA ===")

    load_csv_files(
        ground_truth_files,
        EVALUATION_DB
    )

    print("\n=== DATABASE VERIFICATION ===")

    for database in [OPERATIONAL_DB, EVALUATION_DB]:

        with sqlite3.connect(database) as connection:

            tables = pd.read_sql_query(
                "SELECT name FROM sqlite_master "
                "WHERE type='table' ORDER BY name",
                connection
            )

            print(f"\nDatabase: {database.name}")

            for table in tables["name"]:

                count = pd.read_sql_query(
                    f'SELECT COUNT(*) AS total FROM "{table}"',
                    connection
                )["total"][0]

                print(f"{table}: {count} records")

    print("\nDATABASE LOADING COMPLETED!")


if __name__ == "__main__":
    main()
