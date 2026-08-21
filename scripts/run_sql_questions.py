"""
Phase 3 — Run the SQL business questions against Supabase and print results.

This is a convenience runner so a reviewer can re-execute the queries in
sql/business_questions.sql without opening the Supabase SQL Editor.
Requires the same .env setup as scripts/load_to_supabase.py.
"""

import os
import sys

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_URL = os.getenv("SUPABASE_DB_URL")
SQL_FILE = os.path.join(os.path.dirname(__file__), "..", "sql", "business_questions.sql")


def split_queries(sql_text):
    """Split the .sql file into individual queries on blank-line-separated
    statements terminated by ';', skipping comment-only chunks."""
    statements = [s.strip() for s in sql_text.split(";") if s.strip()]
    return [s for s in statements if not all(line.strip().startswith("--") or not line.strip()
                                              for line in s.splitlines())]


def main():
    if not DB_URL:
        print("ERROR: SUPABASE_DB_URL not found. Check your .env file.")
        sys.exit(1)

    if not os.path.exists(SQL_FILE):
        print(f"ERROR: {SQL_FILE} not found.")
        sys.exit(1)

    with open(SQL_FILE, "r") as f:
        sql_text = f.read()

    queries = split_queries(sql_text)

    conn = psycopg2.connect(DB_URL)
    try:
        with conn.cursor() as cur:
            for i, query in enumerate(queries, start=1):
                print(f"\n{'='*70}\nQuery {i}\n{'='*70}")
                cur.execute(query)
                colnames = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                print(" | ".join(colnames))
                for row in rows[:15]:  # preview first 15 rows
                    print(" | ".join(str(v) for v in row))
                if len(rows) > 15:
                    print(f"... ({len(rows) - 15} more rows)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()