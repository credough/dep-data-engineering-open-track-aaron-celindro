-- Milestone 3 — SQL Business Questions
-- Run against the `fuel_prices` table in Supabase (see scripts/load_to_supabase.py)
--
-- All three queries use the midpoint of (price_low, price_high) as a
-- representative price per row, and only include rows where status = 'reported'
-- (i.e. exclude weeks where a brand had no outlet or didn't submit a report).


-- =====================================================================
-- Question 1: How does the average price per liter change over time,
-- by fuel type?
-- (Directly supports the project's core KPI: price trend by fuel type.)
-- =====================================================================
SELECT
    week_start,
    product,
    ROUND(AVG((price_low + price_high) / 2.0), 2) AS avg_price
FROM fuel_prices
WHERE status = 'reported'
GROUP BY week_start, product
ORDER BY week_start, product;


-- =====================================================================
-- Question 2: Which NCR city has the highest and lowest average fuel
-- prices overall?
--
-- CAVEAT: raw city averages are biased. Marikina, Navotas and Valenzuela only appear
-- from March 2026, when prices were already much higher, so they look expensive for the
-- wrong reason. The fair comparison (each city against the same-week, same-fuel average)
-- is KPI 4: see scripts/kpis.py and docs/KPI_DEFINITIONS.md.
-- =====================================================================
SELECT
    city,
    ROUND(AVG((price_low + price_high) / 2.0), 2) AS avg_price
FROM fuel_prices
WHERE status = 'reported'
GROUP BY city
ORDER BY avg_price DESC;


-- =====================================================================
-- Question 3: Which brand tends to be the cheapest / most expensive
-- across all NCR cities?
--
-- CAVEAT: raw brand averages mix in timing and fuel mix (brands are not sold in every
-- week, city and fuel). The fair comparison (each brand against the same-city, same-week,
-- same-fuel average) is KPI 5: see scripts/kpis.py and docs/KPI_DEFINITIONS.md.
-- =====================================================================
SELECT
    brand,
    ROUND(AVG((price_low + price_high) / 2.0), 2) AS avg_price
FROM fuel_prices
WHERE status = 'reported'
GROUP BY brand
ORDER BY avg_price ASC;


-- =====================================================================
-- Bonus: Week-over-week % change in average price, by fuel type.
-- (Not one of the required 3, but directly supports the project's KPI
-- and is a nice example of a window function.)
-- =====================================================================
WITH weekly_avg AS (
    SELECT
        week_start,
        product,
        AVG((price_low + price_high) / 2.0) AS avg_price
    FROM fuel_prices
    WHERE status = 'reported'
    GROUP BY week_start, product
)
SELECT
    week_start,
    product,
    ROUND(avg_price, 2) AS avg_price,
    ROUND(
        100.0 * (avg_price - LAG(avg_price) OVER (PARTITION BY product ORDER BY week_start))
        / NULLIF(LAG(avg_price) OVER (PARTITION BY product ORDER BY week_start), 0),
        2
    ) AS pct_change_wow
FROM weekly_avg
ORDER BY product, week_start;
