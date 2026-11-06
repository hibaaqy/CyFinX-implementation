from pathlib import Path
import sys

# Locate the project root
ROOT = Path(__file__).resolve().parents[1]

# Add project root to Python import path
sys.path.insert(0, str(ROOT))


from app.database.connection import (
    engine,
    DB_DIR,
    OPERATIONAL_DB_PATH
)

from app.database.models import Base


def main():

    DB_DIR.mkdir(parents=True, exist_ok=True)

    print("Creating CyFinX operational database...")

    Base.metadata.create_all(bind=engine)

    print("\nDatabase created successfully!")
    print(f"Location: {OPERATIONAL_DB_PATH}")

    print("\nTables created:")

    for table_name in sorted(Base.metadata.tables):
        print(f" - {table_name}")

    print(f"\nTotal operational tables: {len(Base.metadata.tables)}")


if __name__ == "__main__":
    main()