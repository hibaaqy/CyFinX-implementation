
from pathlib import Path
import pandas as pd

# Dataset location
DATA_DIR = (
    Path(__file__).resolve().parents[1]
    / "CyFinX_V3_Final_2500_14_CSVs"
)

print("=" * 65)
print("CYFINX DATASET INSPECTION")
print("=" * 65)

if not DATA_DIR.exists():
    raise FileNotFoundError(f"Dataset folder not found: {DATA_DIR}")

csv_files = sorted(DATA_DIR.glob("*.csv"))

print(f"\nTotal CSV files found: {len(csv_files)}")

for file in csv_files:
    print("\n" + "-" * 65)
    print(f"FILE: {file.name}")

    try:
        df = pd.read_csv(file, low_memory=False)

        print(f"Total rows: {len(df)}")
        print(f"Total columns: {len(df.columns)}")
        print("\nColumn names:")

        for column in df.columns:
            print(f"  - {column}")

    except Exception as error:
        print(f"ERROR reading file: {error}")

print("\n" + "=" * 65)
print("DATASET INSPECTION COMPLETED")
print("=" * 65)
