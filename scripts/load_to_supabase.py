"""
Phase 3 — Load processed data into Supabase (Postgres)

Creates the `fuel_prices` table (if it doesn't exist) in your Supabase
project and loads data/processed/ncr_fuel_prices.csv into it.

Safe to re-run: it replaces the table's contents each time, so re-running
after a new transform.py run keeps Supabase in sync with your latest CSV.

Requires a .env file in the project root (NOT committed to git) with:
    SUPABASE_DB_URL=postgresql://postgres.[ref]:[password]@aws-0-[region].pooler.supabase.com:6543/postgres
"""

import os
import sys

import pandas as pd
import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "processed", "ncr_fuel_prices.csv")

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS fuel_prices (
    id SERIAL PRIMARY KEY,
    week_start DATE NOT NULL,
    city TEXT NOT NULL,
    product TEXT NOT NULL,
    brand TEXT NOT NULL,
    price_low NUMERIC,
    price_high NUMERIC,
    status TEXT NOT NULL,
    UNIQUE (week_start, city, product, brand)
);
"""

INSERT_SQL = """
INSERT INTO fuel_prices (week_start, city, product, brand, price_low, price_high, status)
VALUES %s
ON CONFLICT (week_start, city, product, brand) DO UPDATE SET
    price_low = EXCLUDED.price_low,
    price_high = EXCLUDED.price_high,
    status = EXCLUDED.status;
"""

# This pipeline reprocesses the FULL raw history on every run (not an
# incremental append), so the table is fully cleared before reloading.
# An upsert alone is not enough here: it inserts new rows and updates
# matching ones, but never removes rows whose key no longer exists in
# the latest CSV (e.g. a row that was previously mis-parsed due to a
# bug and has since been correctly excluded by transform.py). Without
# this, fixed bugs in transform.py wouldn't actually clean up data
# already sitting in Supabase from an earlier, buggier run.
TRUNCATE_SQL = "TRUNCATE TABLE fuel_prices;"


def main():
    if not DB_URL:
        print("ERROR: SUPABASE_DB_URL not found. Check your .env file exists "
              "in the project root and contains SUPABASE_DB_URL=...")
        sys.exit(1)

    if not os.path.exists(CSV_PATH):
        print(f"ERROR: {CSV_PATH} not found. Run scripts/transform.py first.")
        sys.exit(1)

    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} rows from {CSV_PATH}")

    records = [
        (
            row["week_start"], row["city"], row["product"], row["brand"],
            None if pd.isna(row["price_low"]) else row["price_low"],
            None if pd.isna(row["price_high"]) else row["price_high"],
            row["status"],
        )
        for _, row in df.iterrows()
    ]

    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            print("Creating table if it doesn't exist...")
            cur.execute(CREATE_TABLE_SQL)

            print("Clearing existing rows (full refresh, not incremental)...")
            cur.execute(TRUNCATE_SQL)

            print(f"Inserting {len(records)} rows into fuel_prices...")
            execute_values(cur, INSERT_SQL, records, page_size=1000)

        conn.commit()
        print("Done. Data is now in Supabase.")
    except Exception as exc:
        conn.rollback()
        print(f"ERROR during load, rolled back: {exc}")
        sys.exit(1)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
    