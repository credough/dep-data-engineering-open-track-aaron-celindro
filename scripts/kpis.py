"""
Phase 5 — KPI computation

Turns the processed price table (data/processed/ncr_fuel_prices.csv) into the
project's five KPIs and saves them as small, tidy CSVs in output/kpis/, so the
notebooks and the future dashboard read the same numbers instead of each
recomputing them.

KPIs (full definitions in docs/KPI_DEFINITIONS.md)
  1. avg_price_php_per_liter   NCR average price by fuel type, per bulletin
  2. pct_vs_baseline           % above the pre-shock baseline
  3. wow_pct_change            week-over-week % change (exact 7-day gaps only)
  4. city premium              city price vs the same-week, same-fuel NCR average
  5. brand premium             brand price vs the same-city, same-week, same-fuel average

Outputs (output/kpis/)
  kpi_weekly_by_fuel.csv   KPIs 1-3, one row per bulletin and fuel
  kpi_city_premium.csv     KPI 4, per city and comparison window
  kpi_brand_premium.csv    KPI 5, per brand
  kpi_scorecard.csv        latest / peak snapshot per fuel (dashboard-ready)

The helper functions are importable (see notebooks/segmentation_and_kpis.ipynb).

Usage
  python scripts/kpis.py
  python scripts/kpis.py --shock-start 2026-03-10 --baseline-bulletins 8
"""

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "processed" / "ncr_fuel_prices.csv"
KPI_DIR = ROOT / "output" / "kpis"

# The March 10, 2026 bulletin is missing, so the first bulletin of the price
# shock is Mar 17; anything before this date counts as "pre-shock".
SHOCK_START = pd.Timestamp("2026-03-10")
BASELINE_BULLETINS = 8     # the N bulletins just before the shock form the baseline
MIN_BRANDS_PER_CELL = 3    # a brand is only compared where >= 3 brands report

BRAND_LABELS = {
    "CALTEX": "Caltex", "FLYING": "Flying V", "INDEPENDENT": "Independent",
    "PETRON": "Petron", "PHOENIX": "Phoenix", "PTT": "PTT", "SEAOIL": "Seaoil",
    "SHELL": "Shell", "TOTAL": "Total", "UNIOIL": "Unioil",
}
PRODUCT_LABELS = {"DIESEL": "Diesel", "DIESEL PLUS": "Diesel Plus", "KEROSENE": "Kerosene"}
CITY_LABELS = {"Taguig Cty": "Taguig City"}  # typo in the DOE source

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- loading
def load_prices(path=DATA_FILE):
    """Load the processed CSV, tidy labels, keep reported prices, add `price`
    (midpoint of each brand's reported low-high range)."""
    df = pd.read_csv(path, parse_dates=["week_start"])
    df["city"] = df["city"].replace(CITY_LABELS)
    df["brand"] = df["brand"].replace(BRAND_LABELS)
    df["product"] = df["product"].replace(PRODUCT_LABELS)
    df = df[df["status"] == "reported"].copy()
    df["price"] = (df["price_low"] + df["price_high"]) / 2
    return df


def core_cities(prices):
    """Cities present from the very first bulletin (a consistent panel for trends)."""
    first_seen = prices.groupby("city")["week_start"].min()
    return sorted(first_seen[first_seen == first_seen.min()].index)


def all_cities_start(prices):
    """First bulletin in which every city appears."""
    return prices.groupby("city")["week_start"].min().max()


# --------------------------------------------------------------------------- building blocks
def city_week_prices(prices):
    """Brand midpoints -> one price per (week, city, fuel)."""
    return prices.groupby(["week_start", "city", "product"], as_index=False)["price"].mean()


def ncr_weekly_prices(city_week, cities):
    """NCR average per (week, fuel): average of city prices, so a city with more
    reporting brands does not get more weight. Returns a wide frame (week x fuel)."""
    sub = city_week[city_week["city"].isin(cities)]
    return sub.groupby(["week_start", "product"])["price"].mean().unstack()


def weekly_kpis(ncr, shock_start=SHOCK_START, baseline_bulletins=BASELINE_BULLETINS):
    """KPIs 1-3 in long format (one row per bulletin and fuel)."""
    pre = ncr[ncr.index < shock_start]
    if len(pre) < baseline_bulletins:
        raise ValueError(f"Only {len(pre)} pre-shock bulletins; need {baseline_bulletins} for the baseline.")
    baseline = pre.tail(baseline_bulletins).mean()

    gap_days = ncr.index.to_series().diff().dt.days
    change = (ncr / ncr.shift(1) - 1) * 100            # vs the previous *published* bulletin
    wow = change.where(gap_days.eq(7), np.nan)         # only when exactly one week apart
    vs_baseline = (ncr / baseline - 1) * 100

    def long(frame, name):
        out = frame.copy()
        out.index.name = "week_start"
        out.columns.name = "product"
        return out.reset_index().melt(id_vars="week_start", value_name=name)

    out = long(ncr, "avg_price_php_per_liter")
    for frame, name in [(vs_baseline, "pct_vs_baseline"),
                        (change, "pct_change_vs_prev_bulletin"),
                        (wow, "wow_pct_change")]:
        out = out.merge(long(frame, name), on=["week_start", "product"])
    out["days_since_prev_bulletin"] = out["week_start"].map(gap_days)
    out["period"] = np.where(out["week_start"] < shock_start, "pre-shock", "shock")
    out = out.dropna(subset=["avg_price_php_per_liter"])
    return out.sort_values(["product", "week_start"]).reset_index(drop=True), baseline


def city_premium(city_week, label, cities=None, start=None, end=None):
    """KPI 4. Each city's % difference from the same-week, same-fuel average of the
    cities present, averaged over weeks. Optionally restrict cities / date window."""
    cw = city_week
    if cities is not None:
        cw = cw[cw["city"].isin(cities)]
    if start is not None:
        cw = cw[cw["week_start"] >= start]
    if end is not None:
        cw = cw[cw["week_start"] <= end]
    cw = cw.copy()
    cw["market"] = cw.groupby(["week_start", "product"])["price"].transform("mean")
    cw["premium_pct"] = (cw["price"] / cw["market"] - 1) * 100
    by_week = cw.groupby(["city", "week_start"])["premium_pct"].mean().unstack(0)
    out = pd.DataFrame({"mean_premium_pct": by_week.mean(), "n_weeks": by_week.count()})
    out.insert(0, "window", label)
    return out.rename_axis("city").reset_index()


def add_brand_premium(prices, min_brands=MIN_BRANDS_PER_CELL):
    """Row-level brand premium: each brand's % difference from the average of all
    brands in the same (week, city, fuel) cell. Cells with fewer than `min_brands`
    brands are dropped, since a 'market average' of 1-2 brands is not meaningful."""
    grp = prices.groupby(["week_start", "city", "product"])["price"]
    cell_mean = grp.transform("mean")
    cell_n = grp.transform("count")
    out = prices[cell_n >= min_brands].copy()
    out["premium_pct"] = (out["price"] / cell_mean[out.index] - 1) * 100
    out["premium_php"] = out["price"] - cell_mean[out.index]   # same gap in pesos per liter
    return out


def mean_premium_by(cells, dims, col="premium_pct"):
    """Average premium by `dims`, first within each week, then across weeks, so a
    week with many observations does not outweigh a week with few."""
    dims = list(dims)
    weekly = cells.groupby(dims + ["week_start"])[col].mean()
    return weekly.groupby(dims).mean()


def brand_premium(cells):
    """KPI 5. Per-brand premium (mean of weekly means) with coverage counts."""
    by_week = cells.groupby(["brand", "week_start"])["premium_pct"].mean().unstack(0)
    out = pd.DataFrame({
        "mean_premium_pct": by_week.mean(),
        "n_weeks": by_week.count(),
        "n_rows": cells.groupby("brand").size(),
    })
    return out.rename_axis("brand").reset_index().sort_values("mean_premium_pct").reset_index(drop=True)


def scorecard(weekly, baseline):
    """Latest and peak snapshot per fuel."""
    rows = []
    for product, g in weekly.groupby("product"):
        g = g.sort_values("week_start")
        last, peak = g.iloc[-1], g.loc[g["avg_price_php_per_liter"].idxmax()]
        rows.append({
            "product": product,
            "baseline_price": round(baseline[product], 2),
            "latest_week": last["week_start"].date(),
            "latest_price": round(last["avg_price_php_per_liter"], 2),
            "latest_pct_vs_baseline": round(last["pct_vs_baseline"], 1),
            "peak_week": peak["week_start"].date(),
            "peak_price": round(peak["avg_price_php_per_liter"], 2),
            "peak_pct_vs_baseline": round(peak["pct_vs_baseline"], 1),
        })
    return pd.DataFrame(rows).sort_values("peak_pct_vs_baseline", ascending=False).reset_index(drop=True)


# --------------------------------------------------------------------------- pipeline step
def compute_all(path=DATA_FILE, shock_start=SHOCK_START, baseline_bulletins=BASELINE_BULLETINS):
    prices = load_prices(path)
    cities = core_cities(prices)
    cw = city_week_prices(prices)
    ncr = ncr_weekly_prices(cw, cities)
    weekly, baseline = weekly_kpis(ncr, shock_start, baseline_bulletins)

    start_all = all_cities_start(prices)
    city_kpi = pd.concat([
        city_premium(cw, f"all_cities_from_{start_all:%Y-%m-%d}", start=start_all),
        city_premium(cw, "core_cities_full_history", cities=cities),
    ], ignore_index=True)

    brand_kpi = brand_premium(add_brand_premium(prices))
    return {
        "kpi_weekly_by_fuel": weekly,
        "kpi_city_premium": city_kpi,
        "kpi_brand_premium": brand_kpi,
        "kpi_scorecard": scorecard(weekly, baseline),
    }


def validate(tables):
    """Fail loudly if a KPI table is empty or has impossible values."""
    for name, df in tables.items():
        if df.empty:
            raise ValueError(f"{name} is empty")
    w = tables["kpi_weekly_by_fuel"]
    if (w["avg_price_php_per_liter"] <= 0).any():
        raise ValueError("kpi_weekly_by_fuel contains non-positive prices")
    # Every fuel should have a baseline-relative value in every bulletin.
    if w["pct_vs_baseline"].isna().any():
        raise ValueError("kpi_weekly_by_fuel has missing pct_vs_baseline values")
    logger.info("KPI validation passed (%s)", ", ".join(f"{k}: {len(v)} rows" for k, v in tables.items()))


def main():
    parser = argparse.ArgumentParser(description="Compute the project KPIs from the processed dataset.")
    parser.add_argument("--input", type=Path, default=DATA_FILE, help="processed CSV (default: %(default)s)")
    parser.add_argument("--output-dir", type=Path, default=KPI_DIR, help="where to write KPI CSVs")
    parser.add_argument("--shock-start", type=pd.Timestamp, default=SHOCK_START,
                        help="first date counted as the shock period (default: %(default)s)")
    parser.add_argument("--baseline-bulletins", type=int, default=BASELINE_BULLETINS,
                        help="number of pre-shock bulletins used as the baseline")
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
    print("KPIs complete. Check output/kpis/ for output.")


if __name__ == "__main__":
    main()
