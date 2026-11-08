"""
Run the whole pipeline, in order, with one command.

    ingest -> transform -> kpis -> segments  [-> notebooks]  [-> database]

    1. ingest      scripts/ingest.py     download weekly DOE bulletins (PDF) to data/raw/
    2. transform   scripts/transform.py  parse the PDFs into data/processed/ncr_fuel_prices.csv
    3. kpis        scripts/kpis.py       compute the five KPIs into output/kpis/
    4. segments    scripts/segments.py   build the segment tables into output/segments/
    5. notebooks   (optional)            re-execute both notebooks so charts and tables are fresh
    6. database    (optional)            load the CSV into Supabase and run the SQL questions

By default only steps 1-4 run, so a reviewer needs no database credentials and no
Jupyter kernel. Each step is a separate script, so any step can also be run alone.
The pipeline stops at the first failing step and exits with a non-zero code.

Examples
    python scripts/run_pipeline.py                      # steps 1-4 (needs internet for step 1)
    python scripts/run_pipeline.py --skip-ingest        # reuse the PDFs already in data/raw/
    python scripts/run_pipeline.py --skip-ingest --skip-transform   # only recompute KPIs and segments
    python scripts/run_pipeline.py --with-notebooks     # also refresh the notebooks
    python scripts/run_pipeline.py --with-db            # also load Supabase (needs .env)
"""

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "scripts"
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_FILE = ROOT / "data" / "processed" / "ncr_fuel_prices.csv"
NOTEBOOKS = ["notebooks/insights.ipynb", "notebooks/segmentation_and_kpis.ipynb"]


def run(cmd):
    """Run a command from the repo root, streaming its output. Returns the exit code."""
    return subprocess.run(cmd, cwd=ROOT).returncode


def script(name):
    return [sys.executable, str(SCRIPTS / name)]


def check_raw_pdfs():
    n = len(list(RAW_DIR.glob("*.pdf")))
    if n == 0:
        return f"No PDFs in {RAW_DIR.relative_to(ROOT)}. Check your internet connection and run scripts/ingest.py again."
    print(f"  {n} PDF bulletins in data/raw/")
    return None


def check_processed():
    if not PROCESSED_FILE.exists():
        return f"{PROCESSED_FILE.relative_to(ROOT)} not found. Run without --skip-transform, or run scripts/transform.py."
    return None


def build_steps(args):
    steps = []
    if not args.skip_ingest:
        steps.append(("ingest", lambda: run(script("ingest.py")), check_raw_pdfs))
    if not args.skip_transform:
        steps.append(("transform", lambda: run(script("transform.py")), check_processed))
    steps.append(("kpis", lambda: (check_processed() and 1) or run(script("kpis.py")), None))
    steps.append(("segments", lambda: run(script("segments.py")), None))
    if args.with_notebooks:
        def notebooks():
            for nb in NOTEBOOKS:
                print(f"  executing {nb}")
                code = run([sys.executable, "-m", "jupyter", "nbconvert", "--to", "notebook",
                            "--execute", "--inplace", nb])
                if code != 0:
                    return code
            return 0
        steps.append(("notebooks", notebooks, None))
    if args.with_db:
        steps.append(("load_db", lambda: run(script("load_to_supabase.py")), None))
        steps.append(("sql", lambda: run(script("run_sql_questions.py")), None))
    return steps


def main():
    parser = argparse.ArgumentParser(description="Run the fuel price pipeline end to end.")
    parser.add_argument("--skip-ingest", action="store_true", help="reuse the PDFs already in data/raw/")
    parser.add_argument("--skip-transform", action="store_true", help="reuse the existing processed CSV")
    parser.add_argument("--with-notebooks", action="store_true", help="also re-execute the notebooks")
    parser.add_argument("--with-db", action="store_true", help="also load Supabase and run the SQL questions (needs .env)")
    args = parser.parse_args()

    results = []
    failed = False
    for name, action, post_check in build_steps(args):
        print(f"\n=== {name} " + "=" * (60 - len(name)))
        start = time.time()
        code = action()
        problem = None
        if code == 0 and post_check:
            problem = post_check()
        elapsed = time.time() - start

        if code != 0 or problem:
            print(f"\n[FAILED] {name}: " + (problem or f"exit code {code}"))
            results.append((name, "FAILED", elapsed))
            failed = True
            break
        results.append((name, "ok", elapsed))

    skipped = [n for n, flag in [("ingest", args.skip_ingest), ("transform", args.skip_transform)] if flag]
    print("\n" + "=" * 66 + "\nPipeline summary")
    for name in skipped:
        print(f"  {name:<10} skipped")
    for name, status, elapsed in results:
        print(f"  {name:<10} {status:<7} {elapsed:6.1f}s")
    if failed:
        raise SystemExit(1)
    print("\nDone. KPIs are in output/kpis/, segments in output/segments/.")


if __name__ == "__main__":
    main()
