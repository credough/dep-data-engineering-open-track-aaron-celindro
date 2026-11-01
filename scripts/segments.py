"""
Phase 5 — Segment tables

Builds the four segment comparisons used in notebooks/segmentation_and_kpis.ipynb
and saves them as CSVs in output/segments/, so the results live in files (not
only in notebook cells) and the notebook just reads and presents them.

Segments (2 dimensions each)
  segment_fuel_by_month.csv    fuel x month        mean % above the pre-shock baseline
  segment_brand_by_fuel.csv    brand x fuel        brand premium (%), with sample sizes
  segment_brand_by_period.csv  brand x period      brand premium in % and in pesos per liter
  segment_city_by_period.csv   city x period       city premium (%), 9 long-running cities

"Period" splits the data at the March 2026 price shock: `calm` = bulletins before
the shock, `shock` = bulletins from Mar 17, 2026 onward (see scripts/kpis.py).
Premiums are always measured against a same-week, same-fuel average, never a raw
average, so a segment is not penalised for being measured in a pricier week.

Usage
  python scripts/segments.py
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

import kpis as K

ROOT = Path(__file__).resolve().parent.parent
SEGMENT_DIR = ROOT / "output" / "segments"
MIN_ROWS = 30  # brand x fuel cells with fewer observations are flagged as low-sample

logger = logging.getLogger(__name__)


def fuel_by_month(weekly):
    """Time cohort: mean % above baseline per fuel and calendar month."""
    w = weekly.copy()
    w["month"] = w["week_start"].dt.strftime("%Y-%m")
    out = (w.groupby(["product", "month"])
             .agg(mean_pct_vs_baseline=("pct_vs_baseline", "mean"),
                  bulletins=("week_start", "nunique"))
             .reset_index())
    return out


def brand_by_fuel(cells):
    prem = K.mean_premium_by(cells, ["brand", "product"]).rename("premium_pct")
    counts = cells.groupby(["brand", "product"]).agg(n_rows=("price", "size"),
                                                     n_weeks=("week_start", "nunique"))
    out = counts.join(prem).reset_index()
    out["low_sample"] = out["n_rows"] < MIN_ROWS
    return out[["brand", "product", "premium_pct", "n_rows", "n_weeks", "low_sample"]]


def add_period(df, shock_start):
    df = df.copy()
    df["period"] = np.where(df["week_start"] < shock_start, "calm", "shock")
    return df


def brand_by_period(cells, shock_start):
    c = add_period(cells, shock_start)
    pct = K.mean_premium_by(c, ["brand", "period"], "premium_pct").rename("premium_pct")
    php = K.mean_premium_by(c, ["brand", "period"], "premium_php").rename("premium_php")
    counts = c.groupby(["brand", "period"]).agg(n_rows=("price", "size"), n_weeks=("week_start", "nunique"))
    avg_price = (c.assign(cell_mean=c["price"] - c["premium_php"])
                  .groupby("period")["cell_mean"].mean().rename("avg_market_price"))
    out = counts.join(pct).join(php).reset_index().merge(avg_price.reset_index(), on="period")
    return out[["brand", "period", "premium_pct", "premium_php", "avg_market_price", "n_rows", "n_weeks"]]


def city_by_period(city_week, cities, shock_start):
    day = pd.Timedelta(days=1)
    calm = K.city_premium(city_week, "calm", cities=cities, end=shock_start - day)
    shock = K.city_premium(city_week, "shock", cities=cities, start=shock_start)
    out = pd.concat([calm, shock], ignore_index=True)
    return out.rename(columns={"window": "period", "mean_premium_pct": "premium_pct"})


def compute_all(path=K.DATA_FILE, shock_start=K.SHOCK_START, baseline_bulletins=K.BASELINE_BULLETINS):
    prices = K.load_prices(path)
    cities = K.core_cities(prices)
    city_week = K.city_week_prices(prices)
    ncr = K.ncr_weekly_prices(city_week, cities)
    weekly, _ = K.weekly_kpis(ncr, shock_start, baseline_bulletins)
    cells = K.add_brand_premium(prices)
    return {
        "segment_fuel_by_month": fuel_by_month(weekly),
        "segment_brand_by_fuel": brand_by_fuel(cells),
        "segment_brand_by_period": brand_by_period(cells, shock_start),
        "segment_city_by_period": city_by_period(city_week, cities, shock_start),
    }


def validate(tables):
    for name, df in tables.items():
        if df.empty:
            raise ValueError(f"{name} is empty")
    periods = set(tables["segment_brand_by_period"]["period"])
    if periods != {"calm", "shock"}:
        raise ValueError(f"expected calm and shock periods, got {periods}")
    logger.info("Segment validation passed (%s)", ", ".join(f"{k}: {len(v)} rows" for k, v in tables.items()))


def main():
    parser = argparse.ArgumentParser(description="Build the segment comparison tables.")
    parser.add_argument("--input", type=Path, default=K.DATA_FILE)
    parser.add_argument("--output-dir", type=Path, default=SEGMENT_DIR)
    parser.add_argument("--shock-start", type=pd.Timestamp, default=K.SHOCK_START)
    parser.add_argument("--baseline-bulletins", type=int, default=K.BASELINE_BULLETINS)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if not args.input.exists():
        raise SystemExit(f"{args.input} not found. Run scripts/transform.py first.")

    try:
        tables = compute_all(args.input, args.shock_start, args.baseline_bulletins)
        validate(tables)
    except ValueError as exc:
        raise SystemExit(f"ERROR: {exc}")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    for name, df in tables.items():
        out = df.copy()
        numeric = out.select_dtypes("number").columns
        out[numeric] = out[numeric].round(3)
        out.to_csv(args.output_dir / f"{name}.csv", index=False)
        logger.info("Saved %s", args.output_dir / f"{name}.csv")
    print("Segments complete. Check output/segments/ for output.")


if __name__ == "__main__":
    main()
