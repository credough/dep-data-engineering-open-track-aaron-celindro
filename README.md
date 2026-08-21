# Philippine Fuel Price Data Pipeline

## Problem Statement
I want to answer: "How have Philippine retail fuel prices (gasoline, diesel, kerosene) changed over time, and how do they vary by region and fuel type?"

## How to Run

```bash
pip install -r requirements.txt

python scripts/ingest.py              # 1. download weekly PDF bulletins to data/raw/
python scripts/transform.py           # 2. parse PDFs into data/processed/ncr_fuel_prices.csv
python scripts/load_to_supabase.py    # 3. load the clean dataset into Supabase
python scripts/run_sql_questions.py   # 4. run and print the SQL business questions
```

Requires a `.env` file in the project root with `SUPABASE_DB_URL=<your Supabase connection string>` (not committed to git).

## Audience
This project is for consumers, journalists and researchers, and technical reviewers (recruiters, hiring managers, data engineers) evaluating real-world Data Engineering skills.

## KPI or Key Metric
The main metric I want to track is average retail price per liter, by fuel type and region, over time, with week-over-week percent change as a secondary derived metric.

## Likely Data Source
I will explore the DOE Oil Monitor bulletins and GlobalPetrolPrices.com's Philippines gasoline series.
DOE Oil Monitor: https://doe.gov.ph/articles/group/liquid-fuels?category=Oil+Monitor&display_type=Card
GlobalPetrolPrices.com: https://www.globalpetrolprices.com/Philippines/gasoline_prices/

## Possible Final Dashboard
The dashboard should help the audience quickly see current DOE prices, historical trends by fuel type, and regional comparisons, enough to answer "is now a good time to fill up, and how does my region compare?" at a glance.

## Data Source Notes

### Primary Source
- Name: DOE NCR Price Monitoring (Department of Energy, Philippines — Oil Industry Management Bureau)
- URL pattern: `https://prod-cms.doe.gov.ph/documents/d/guest/ncr-price-monitoring-{MMDDYYYY}-pdf`
  (e.g. `ncr-price-monitoring-07082025-pdf` for the bulletin dated July 8, 2025)
- Format: PDF bulletins, one per week, containing a price table (product, overall price range, common price) plus a per-city breakdown for NCR (Makati, Pasay, Parañaque, Muntinlupa, etc.)
- Coverage: Prevailing pump prices by fuel type (gasoline RON91/95/97, diesel, diesel plus, kerosene) for NCR, published weekly since at least January 2024
- Why it fits the problem: This is the authoritative primary source for Philippine fuel prices, with the city-level granularity needed to answer the problem statement
- Known limitations:
  - DOE does not publish every single week without exception — some weeks return a 404 (~19% of weeks in an initial test run), likely due to holidays or schedule shifts. Ingestion treats a missing week as an expected, non-fatal outcome, not a failure.
  - This URL pattern currently covers **NCR only**. Regional coverage (South/North Luzon, Visayas, Mindanao) uses a related but distinct URL pattern and naming convention on the same `prod-cms.doe.gov.ph` host, to be added in a later ingestion pass.
  - `doe.gov.ph`'s article listing pages (the human-facing bulletin index) are protected by bot detection and could not be crawled directly; `prod-cms.doe.gov.ph`, which hosts the actual PDF files, was not blocked and was used instead, with a predictable date-based URL built directly rather than discovered via crawling.
  - robots.txt on `doe.gov.ph` was checked and does not disallow this content.

### Fallback Source
- Name: GlobalPetrolPrices.com — Philippines Gasoline Prices
- URL: https://www.globalpetrolprices.com/Philippines/gasoline_prices/
- Format: CSV/API (downloadable data, weekly series)
- Coverage: Weekly Octane-95 gasoline price for the Philippines, national aggregate, from 2015-12-28 to present, sourced from the DOE
- Why it could still work: If the primary DOE source is temporarily blocked or a bulletin is missing, this provides a continuous, DOE-sourced weekly price series to fill gaps or cross-validate extracted values
- Known limitations: Single national aggregate value only — no brand or regional breakdown, and no diesel/kerosene series, so it cannot fully substitute for the primary source, only supplement it


## Data Ingestion

`scripts/ingest.py` downloads weekly NCR fuel price bulletins (PDF) directly from DOE by constructing predictable URLs for each week in a configurable date range, and saves each one to `data/raw/`.

### How to run
```bash
pip install -r requirements.txt
python scripts/ingest.py
```

Downloaded files are saved as `data/raw/ncr_price_monitoring_YYYY-MM-DD.pdf`. The script logs each attempt; weeks with no published bulletin are skipped (not treated as errors) and logged as such.

### Configuration
The date range is controlled by `START_DATE` and `END_DATE` in `scripts/ingest.py`. The default range currently pulls roughly a year of historical data (~59 weekly attempts, ~48 successful downloads in initial testing).

## Schema Plan

### Main Table
- **Name:** `fuel_prices` (stored as `data/processed/ncr_fuel_prices.csv`, also loaded into Supabase Postgres for SQL analysis)
- **Grain:** one row = one reported fuel price for a specific **brand**, in a specific **city**, for a specific **product (fuel type)**, in a specific **week**
- **Primary key:** composite — (`week_start`, `city`, `product`, `brand`)

### Important Columns

| Column | Meaning | Expected Type |
|---|---|---|
| week_start | Start date (Monday) of the bulletin's coverage week | DATE |
| city | NCR city/municipality where the price was monitored | TEXT |
| product | Fuel type: RON 100, RON 97, RON 95, RON 91, Diesel, Diesel Plus, Kerosene | TEXT |
| brand | Oil company: Petron, Shell, Caltex, Phoenix, Total, Flying V, Unioil, Seaoil, PTT, Independent | TEXT |
| price_low | Lower end of the reported price range (₱/liter) for that brand that week | NUMERIC, nullable |
| price_high | Upper end of the reported price range (₱/liter) for that brand that week | NUMERIC, nullable |
| status | `reported` (has a price), `no_report` (brand has an outlet but didn't submit a price that week), or `unrecognized` (parsing couldn't confidently interpret the cell) | TEXT |

Rows where a brand has **no outlet at all** in a given city are not stored — they're intentionally excluded during parsing rather than represented as null rows, since "no outlet" and "no report" are meaningfully different and only the latter is worth tracking as a gap.

### Related Tables/Files
- **Raw source:** `data/raw/*.pdf` — one PDF per week, the original DOE bulletins. Not joined to `fuel_prices`; kept as the immutable source of truth in case reprocessing is ever needed.
- No other processed tables currently exist. If regional data (South/North Luzon, Visayas, Mindanao) is added later, it would join on the same (`week_start`, `product`, `brand`) grain with `city` disambiguated by region.

### Why this grain
The project's core KPI — *average price per liter, by fuel type and region, over time, with week-over-week % change* — requires aggregating up (e.g. across brands for a city+week, or across cities for a week) without losing underlying detail. Storing at the most granular level means every rollup the analysis phase needs is just a `GROUP BY` away, rather than needing to re-parse PDFs for a different level of detail later.

## Data Processing

`scripts/transform.py` parses every weekly bulletin PDF in `data/raw/`
into a single clean, long-format dataset saved to `data/processed/ncr_fuel_prices.csv`.

## SQL Business Questions

`data/processed/ncr_fuel_prices.csv` is loaded into a Supabase (Postgres) database via `scripts/load_to_supabase.py`, and queried with `sql/business_questions.sql` to answer three core questions from the problem statement.

### How to run
```bash
# 1. Set up a Supabase project and add SUPABASE_DB_URL to a .env file
#    in the project root (see .env.example)
python scripts/load_to_supabase.py     # loads the processed CSV into Supabase
python scripts/run_sql_questions.py    # runs and prints all queries
```

### Questions answered
1. **How does the average price per liter change over time, by fuel type?** — supports the project's core trend KPI.
2. **Which NCR city has the highest and lowest average fuel prices overall?**
3. **Which brand tends to be the cheapest / most expensive across all NCR cities?**

A bonus fourth query computes week-over-week % change in average price by fuel type, directly supporting the project's secondary KPI.

### Load strategy
`load_to_supabase.py` does a **full refresh** (truncate + reinsert) on every run, since this pipeline reprocesses the full raw history each time rather than appending incrementally. See "Known data quality findings" above for why this matters.

### Output
One row per (week_start, city, product, brand):

| Column | Description |
|---|---|
| week_start | Monday of the bulletin's coverage week (from filename) |
| city | NCR city/municipality |
| product | Fuel type (RON 100, RON 97, RON 95, RON 91, Diesel, Diesel Plus, Kerosene) |
| brand | Oil company (Petron, Shell, Caltex, Phoenix, Total, Flying V, Unioil, Seaoil, PTT, Independent) |
| price_low / price_high | Reported price range (₱/liter) for that brand that week |
| status | `reported`, `no_report` (brand has an outlet but didn't submit a price that week), or `unrecognized` |

### How to run
```bash
pip install -r requirements.txt
python scripts/transform.py
```

### Why a custom parser instead of a standard PDF-table library
The bulletin's rows are visually split across two overlapping text lines
(numbers vs. labels), which breaks automatic table detection. This script
instead reads each word's exact position on the page and reconstructs
rows/columns from measured coordinates.

### Known data quality findings (discovered during development)
- **Source format drift**: DOE changed the bulletin's column positions in
  early 2026, then switched to a completely different page size (~2.4x
  larger) by April 2026. The parser measures each PDF's own header row at
  runtime instead of using fixed coordinates, so it adapts automatically
  rather than silently failing when the source changes.
- **Template artifact**: every bulletin checked (Jul 2025 – Aug 2026) has
  a hidden, leftover duplicate of "Caloocan City" rendered almost exactly
  on top of page 2's first city label. This is a quirk in DOE's own Excel
  template, not a bug in this script. It's filtered at the parsing stage,
  and backed by a second safety net: every parsed city is checked against
  a whitelist of known real NCR cities, since the pixel offset between
  the ghost text and the real label wasn't always large enough for the
  parsing-stage fix alone to catch it on every single week.
- **Split city blocks**: as DOE added more NCR cities to the report
  (12 cities by 2026 vs. 9 originally), some cities' data now splits
  across the page 1/page 2 boundary. The parser tracks the last known
  city across the whole document to handle this correctly.
- **Validation drops**: of 13,257 parsed rows, 60 (0.45%) were dropped —
  12 with non-positive prices, and 48 with an unrecognized city value
  caught by the whitelist safeguard above. Both are logged with the exact
  bad value(s) so they're traceable, not silently discarded.
- **Supabase load strategy**: the load script does a full table refresh
  (truncate + reinsert) on every run rather than an upsert-only append.
  An upsert alone inserts new rows and updates matching ones, but never
  removes rows whose key no longer exists in the latest CSV — during
  development, a bug fix in `transform.py` correctly stopped producing a
  bad row, but the *already-loaded* bad row stayed in Supabase until the
  load strategy was changed to a full refresh.

### Result
48 weekly bulletins (Jul 2025 – Aug 2026) → 13,197 clean rows in
`data/processed/ncr_fuel_prices.csv`.