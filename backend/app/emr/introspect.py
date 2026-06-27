"""
EMR database introspection script.

Usage:
    cd backend
    python -m app.emr.introspect

This script connects to the EMR database (read-only) and reports
schemas, tables, and columns that look patient-related.
No actual patient data is printed.
"""

import sys
import logging
from sqlalchemy import create_engine, inspect, text

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger(__name__)

PATIENT_TABLE_KEYWORDS = {"patient", "client", "person", "demographic", "member", "subscriber"}
PATIENT_COLUMN_KEYWORDS = {"first", "last", "dob", "birth", "phone", "email", "address", "name", "ssn", "sex", "gender"}


def run_introspection() -> None:
    try:
        from app.core.config import get_settings
        settings = get_settings()
        url = settings.EMR_DATABASE_URL
    except Exception:
        import os
        url = os.environ.get("EMR_DATABASE_URL", "")

    if not url:
        print("ERROR: EMR_DATABASE_URL is not set. Add it to backend/.env first.")
        sys.exit(1)

    print(f"\nConnecting to EMR database...")
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 10})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Connection successful.\n")
    except Exception as exc:
        print(f"ERROR: Could not connect to EMR database: {exc}")
        sys.exit(1)

    inspector = inspect(engine)
    schemas = inspector.get_schema_names()
    print(f"Available schemas: {schemas}\n")

    print("=" * 60)
    print("PATIENT-RELATED TABLES FOUND:")
    print("=" * 60)

    found_any = False
    for schema in schemas:
        if schema in ("pg_catalog", "information_schema"):
            continue
        try:
            tables = inspector.get_table_names(schema=schema)
        except Exception:
            continue

        for table in tables:
            lower_table = table.lower()
            if any(kw in lower_table for kw in PATIENT_TABLE_KEYWORDS):
                found_any = True
                print(f"\n  Schema: {schema}  |  Table: {table}")
                try:
                    columns = inspector.get_columns(table, schema=schema)
                    matched_cols = [
                        c["name"]
                        for c in columns
                        if any(kw in c["name"].lower() for kw in PATIENT_COLUMN_KEYWORDS)
                    ]
                    all_cols = [c["name"] for c in columns]
                    print(f"    All columns ({len(all_cols)}): {', '.join(all_cols)}")
                    print(f"    Patient-relevant columns: {', '.join(matched_cols) or 'none detected'}")
                except Exception as col_exc:
                    print(f"    Could not read columns: {col_exc}")

    if not found_any:
        print("\n  No tables matched patient-related keywords.")
        print("  Try searching manually with the column scan below.\n")

    print("\n" + "=" * 60)
    print("COLUMNS CONTAINING PATIENT KEYWORDS (all tables):")
    print("=" * 60)

    for schema in schemas:
        if schema in ("pg_catalog", "information_schema"):
            continue
        try:
            tables = inspector.get_table_names(schema=schema)
        except Exception:
            continue

        for table in tables:
            try:
                columns = inspector.get_columns(table, schema=schema)
            except Exception:
                continue
            matched = [
                c["name"]
                for c in columns
                if any(kw in c["name"].lower() for kw in PATIENT_COLUMN_KEYWORDS)
            ]
            if matched:
                print(f"\n  {schema}.{table}: {', '.join(matched)}")

    print("\nIntrospection complete. Use these results to update talbot_adapter.py.")
    print("Review the adapter SELECT and EMRPatient mapping before wiring new fields.\n")


if __name__ == "__main__":
    run_introspection()
