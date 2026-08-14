# Philippine Fuel Price Data Pipeline

## Problem Statement
I want to answer: "How have Philippine retail fuel prices (gasoline, diesel, kerosene) changed over time, and how do they vary by region and fuel type?"

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