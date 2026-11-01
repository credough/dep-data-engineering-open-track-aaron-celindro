# KPI Definitions

This project answers one question: **how have Philippine retail fuel prices changed over time, and how do they vary by region and fuel type?** The five KPIs below measure exactly that, and each one traces back to a part of the question.

All KPIs are computed by [`scripts/kpis.py`](../scripts/kpis.py) from `data/processed/ncr_fuel_prices.csv` and saved to `output/kpis/`. They are presented in [`notebooks/segmentation_and_kpis.ipynb`](../notebooks/segmentation_and_kpis.ipynb).

| # | KPI | Answers | Grain | Saved in |
|---|-----|---------|-------|----------|
| 1 | NCR average price (₱ per liter) | How high are prices? | fuel x bulletin | `kpi_weekly_by_fuel.csv` |
| 2 | % above baseline | How far are prices from normal? | fuel x bulletin | `kpi_weekly_by_fuel.csv` |
| 3 | Week-over-week % change | How fast are prices moving? | fuel x bulletin | `kpi_weekly_by_fuel.csv` |
| 4 | City premium | How do places vary? | city x window | `kpi_city_premium.csv` |
| 5 | Brand premium | How do sellers vary? | brand | `kpi_brand_premium.csv` |

A latest/peak snapshot of KPIs 1 and 2 is in `kpi_scorecard.csv`.

## Shared building blocks

- **Price.** For each brand, city, fuel and week, DOE reports a low and a high price. The **price** used everywhere is the midpoint, `(price_low + price_high) / 2`. Only rows with `status = reported` are used; `no_report` rows carry no price.
- **City price.** The average of the brand prices in that city, fuel and week.
- **NCR price.** The average of the city prices for the **9 cities present in every bulletin** (Caloocan, Makati, Manila, Muntinlupa, Parañaque, Pasay, Pasig, Quezon City, Taguig). Marikina, Navotas and Valenzuela only appear from March 17, 2026, so including them in a trend would make prices look like they jumped when the city list changed. Averaging city prices (rather than all brand prices) keeps a city with more reporting brands from carrying more weight.
- **Shock and baseline.** The March 2026 price jump is the dividing line. The **baseline** is the average NCR price of the **8 bulletins just before the shock** (January 13 to March 3, 2026). The **shock period** is every bulletin from March 17, 2026 onward (the March 10 bulletin is missing). Both are parameters (`--shock-start`, `--baseline-bulletins`), not hard-coded assumptions.

---

## KPI 1: NCR average price (₱ per liter)

**Definition.** What a typical liter of each fuel costs in Metro Manila in a given bulletin.

**Formula.** NCR price = mean over the 9 core cities of (mean over reporting brands of the brand's price midpoint).

**Why it matters.** It is the most direct measure of "how have prices changed over time", by fuel type.

**Column.** `avg_price_php_per_liter`

**Latest values (Aug 4, 2026).** Diesel ₱90.85, Diesel Plus ₱96.20, Kerosene ₱120.57, RON 91 ₱80.61, RON 95 ₱83.55, RON 97 ₱89.06, RON 100 ₱89.86.

**Read with care.** A single all-period average of this KPI is misleading: the shock pulls the mean far above the typical calm price (diesel's mean over the whole period is ₱71.6, against a median of ₱57.3). Always say which period a level refers to.

## KPI 2: % above baseline

**Definition.** How far a fuel's price sits above its own calm, pre-shock level.

**Formula.** `(NCR price / baseline price - 1) x 100`, where the baseline is that fuel's average NCR price over the 8 bulletins before the shock.

**Why it matters.** It puts fuels with very different price levels on one scale (a ₱20 rise means something different for ₱56 diesel and ₱120 kerosene), and it shows both the peak and how much of the shock has unwound.

**Column.** `pct_vs_baseline`

**Values.** Peak (all fuels, Apr 7, 2026): Diesel +161.8%, Diesel Plus +145.3%, Kerosene +96.7%, RON 91 +70.8%, RON 95 +67.7%, RON 100 +60.2%, RON 97 +58.9%. Latest (Aug 4, 2026): Diesel +60.4%, Diesel Plus +50.8%, Kerosene +44.7%, RON 91 +43.4%, RON 95 +39.9%, RON 97 +36.0%, RON 100 +35.4%.

**Read with care.** Kerosene was already rising before the shock (about ₱74 in July 2025 to ₱87 by March 3, 2026), so its baseline already contains some increase.

## KPI 3: Week-over-week % change

**Definition.** How fast the NCR price is moving from one bulletin to the next.

**Formula.** `(NCR price / price in the previous bulletin - 1) x 100`, **reported only when the two bulletins are exactly 7 days apart.**

**Why it matters.** It is the project's secondary KPI: a calm market has small weekly moves, a volatile one has large moves in both directions.

**Columns.** `wow_pct_change` (exact 7-day gaps only), `pct_change_vs_prev_bulletin` (any gap), `days_since_prev_bulletin` (so a reader can see which is which).

**Why the 7-day rule.** Nine weekly bulletins are missing, so some "previous bulletins" are two or three weeks back. For example, the March 17, 2026 bulletin follows March 3, so diesel's +80.3% on that date covers 14 days, not one week; `wow_pct_change` is left empty there rather than overstating the one-week move.

**Values.** Diesel's largest 7-day rise is +15.6% (Mar 24, 2026) and its largest fall is -19.8% (Apr 21, 2026).

## KPI 4: City premium

**Definition.** Whether a city's fuel runs above or below the NCR market, after removing the effect of time and fuel type.

**Formula.** For each week and fuel, the market is the average of the city prices in that week. The city's premium is `(city price / market - 1) x 100`, averaged over fuels within a week and then over weeks.

**Why it matters.** This is the "how do prices vary by region" part of the question (here, by NCR city). Comparing against the same-week, same-fuel market means a city is never penalised for being measured in a pricier week.

**Windows.** `all_cities_from_2026-03-17` (all 12 cities, the fair like-for-like comparison, 19 bulletins) and `core_cities_full_history` (the 9 long-running cities, 48 bulletins).

**Values.** Highest: Pasay (+2.47% in the all-cities window, +3.29% over the full history). Lowest: Marikina (-3.16%, only 19 bulletins of history) and Quezon City (-2.22% over the full history).

**Read with care.** Gaps are small, roughly ₱1 to ₱3 per liter at typical prices. The raw average price per city is not a valid KPI: a city that only appears in the expensive months looks expensive for the wrong reason.

## KPI 5: Brand premium

**Definition.** Whether a brand prices above or below the market, after removing the effect of city, time and fuel type.

**Formula.** For each (week, city, fuel) "cell", the market is the average of all brand prices in that cell. The brand's premium is `(brand price / cell average - 1) x 100`, averaged within each week and then over weeks. Cells with fewer than 3 brands are excluded, since an average of one or two brands is not a meaningful market. The same gap in pesos (`price - cell average`) is also computed for the segmentation work.

**Why it matters.** It measures how much the choice of seller changes the price a consumer pays.

**Columns.** `mean_premium_pct`, plus `n_weeks` and `n_rows` so a reader can see how much data stands behind each number.

**Values.** Shell +6.05%, Caltex +4.43%, Total +3.95%, Unioil +0.14%, Phoenix -0.08%, Petron -3.17%, Seaoil -3.41%, PTT -4.17%, Independent -5.01%, Flying V -5.80%.

**Read with care.** "Independent" is a group of unbranded stations, not one company. Kerosene and RON 100 are not covered because too few brands report them in the same city and week.

---

## KPIs vs vanity metrics

| Tempting number | Why it is not used | KPI used instead |
|---|---|---|
| Average price over the whole period | Mixes calm and shock months, so it describes neither | KPI 1 and 2, with a named baseline |
| Raw average price per city or brand | Depends on *when* the city or brand was measured | KPI 4 and 5, always against the same-week, same-fuel market |
| "Change since last week" for every bulletin | Misleading when bulletins are missing | KPI 3, only for exact 7-day gaps |

## Reproducing the KPIs

```bash
python scripts/kpis.py
# or the whole pipeline:  python scripts/run_pipeline.py --skip-ingest
```
