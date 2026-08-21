"""
Phase 3 — Data Transformation

Parses the weekly DOE "NCR Price Monitoring" PDF bulletins in data/raw/
into a single clean, long-format dataset saved to data/processed/.

Output grain: one row per (week_start, city, product, brand)
Columns: week_start, city, product, brand, price_low, price_high, status

Why a positional parser instead of pdfplumber's extract_tables():
The bulletin's product rows are visually split across two overlapping
lines (numbers vs. labels), which confuses automatic table detection
and silently merges/misaligns cells. Instead, we read each word's exact
(x, y) position on the page and bucket it into a known column band
(brand) and row (product).

IMPORTANT — column positions are measured PER PAGE, not hardcoded:
Comparing real bulletins across time (Jul 2025 -> Nov 2025 -> Mar 2026
-> Apr 2026) showed DOE's export has drifted more than once: column
x-positions shifted slightly by early 2026, and by April 2026 the PDF
is generated at a completely different page size (roughly 2.4x larger
canvas) with proportionally different coordinates. A parser hardcoded
to one sample file's pixel positions silently returns zero rows once
the source drifts. Instead, this script re-detects each page's own
header row (AREA, PRODUCT, PETRON, SHELL, ..., OVERALL, COMMON) and
builds that page's column bands from those measured positions, so it
adapts automatically regardless of scale or minor margin changes.

Known limitations (see README for details):
- Only the main per-city brand table is parsed. The NCR-wide aggregate
  summary table at the end of each bulletin (Product / Overall Range /
  Common Price only, no city or brand breakdown) is not parsed, since
  it's redundant with data we can already compute ourselves.
- KNOWN SOURCE ARTIFACT: every bulletin checked so far (spanning both
  the old and new page formats) has a leftover, invisible-on-screen
  duplicate of the text "Caloocan City" rendered almost exactly on top
  of the first city label on page 2 (whichever city that is -- it has
  been "Makati City" and, in a later format, "Muntinlupa City"),
  offset by under 1 point vertically. This is a template artifact in
  the source file, not a bug in this script. pdfplumber's default
  word-grouping tolerance is loose enough to interleave the two
  overlapping strings character-by-character, producing garbage like
  "CMalaokoactai nC iCtyity". We work around this with a tight
  y_tolerance when extracting words (separates the two overlapping
  lines cleanly) and by explicitly discarding the known "Caloocan
  City" ghost label whenever a block yields more than one distinct
  area label at that position.
- If DOE ever renames a brand column or removes one entirely, header
  detection for that brand will fail and the script will raise a clear
  error for that file rather than silently producing wrong columns.
"""

import os
import re
import glob
import logging
from collections import defaultdict

import pdfplumber
import pandas as pd

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
PROCESSED_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "processed")
OUTPUT_FILE = os.path.join(PROCESSED_DATA_DIR, "ncr_fuel_prices.csv")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Header labels we look for on every page, in left-to-right column order.
# "FLYING" anchors the "FLYING V" column; the trailing "V" word is ignored.
HEADER_LABELS_IN_ORDER = [
    "PETRON", "SHELL", "CALTEX", "PHOENIX", "TOTAL", "FLYING",
    "UNIOIL", "SEAOIL", "PTT", "INDEPENDENT", "OVERALL", "COMMON",
]
BRAND_NAMES = ["PETRON", "SHELL", "CALTEX", "PHOENIX", "TOTAL", "FLYING",
               "UNIOIL", "SEAOIL", "PTT", "INDEPENDENT"]

PRODUCT_SEQUENCE = ["RON 100", "RON 97", "RON 95", "RON 91", "DIESEL", "DIESEL PLUS", "KEROSENE"]

HEADER_Y_WINDOW = 15   # points; header labels may wrap onto a nearby line
ROW_CLUSTER_TOLERANCE = 4  # points; groups the "numbers line" and "labels line" of one row
WORD_Y_TOLERANCE = 0.5     # tight tolerance to separate overlapping duplicate text layers

KNOWN_GHOST_LABELS = {"Caloocan City"}

# Whitelist of real NCR cities/municipalities DOE has covered so far
# (grew from 9 to 12 cities as DOE expanded coverage during 2025-2026).
# Any parsed "city" value NOT in this set is almost certainly corrupted
# text (e.g. the known overlapping-label artifact defeating our
# separation logic on some week where the pixel offset was smaller than
# expected) and is dropped as a data quality safeguard rather than
# silently kept. See validate().
KNOWN_VALID_CITIES = {
    "Caloocan City", "Quezon City", "Manila City", "Pasig City", "Taguig Cty",
    "Makati City", "Parañaque City", "Muntinlupa City", "Pasay City",
    "Marikina City", "Valenzuela City", "Navotas City",
}

FILENAME_DATE_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def find_header_positions(page):
    """
    Locate this page's header row and return {label: x0} for AREA, PRODUCT,
    and every brand/summary column. Returns None if no header is found
    (e.g. a page that isn't a data table).
    """
    words = page.extract_words()
    area_word = next((w for w in words if w["text"] == "AREA"), None)
    if area_word is None:
        return None

    window = [w for w in words if abs(w["top"] - area_word["top"]) <= HEADER_Y_WINDOW]
    positions = {}
    for w in window:
        if w["text"] in ("AREA", "PRODUCT") or w["text"] in HEADER_LABELS_IN_ORDER:
            positions.setdefault(w["text"], w["x0"])
    return positions


def build_column_bands(positions, page_width):
    """
    Given detected header x-positions, build (name, left, right) bands.
    Boundaries are midpoints between consecutive header anchors.
    """
    ordered_labels = ["AREA", "PRODUCT"] + HEADER_LABELS_IN_ORDER
    missing = [lbl for lbl in ordered_labels if lbl not in positions]
    if missing:
        raise ValueError(f"Could not find header column(s): {missing}")

    anchors = [(lbl, positions[lbl]) for lbl in ordered_labels]
    bands = {}
    for i, (name, x) in enumerate(anchors):
        left = (anchors[i - 1][1] + x) / 2 if i > 0 else 0
        right = (x + anchors[i + 1][1]) / 2 if i < len(anchors) - 1 else page_width
        bands[name] = (left, right)
    return bands


def band_for_x(x, bands, names):
    for name in names:
        left, right = bands[name]
        if left <= x < right:
            return name
    return None


def cluster_rows(words):
    words_sorted = sorted(words, key=lambda w: w["top"])
    clusters = []
    for w in words_sorted:
        placed = False
        for c in clusters:
            if abs(c["top"] - w["top"]) <= ROW_CLUSTER_TOLERANCE:
                c["words"].append(w)
                placed = True
                break
        if not placed:
            clusters.append({"top": w["top"], "words": [w]})
    clusters.sort(key=lambda c: c["top"])
    return clusters


def parse_price_cell(tokens):
    if not tokens:
        return None, None, "no_outlet"

    texts = [t[1] for t in tokens]
    if "NO" in texts and "LFRO" in texts:
        return None, None, "no_report"

    numeric = []
    for t in texts:
        try:
            numeric.append(float(t))
        except ValueError:
            continue

    if len(numeric) >= 2:
        return min(numeric), max(numeric), "reported"
    if len(numeric) == 1:
        return numeric[0], numeric[0], "reported"
    return None, None, "unrecognized"


def parse_page_rows(page):
    """Parse one page into a flat list of {area_label, product, brand_prices}
    row-dicts, WITHOUT grouping into city blocks -- a city's 7-row block can
    split across a page boundary (observed in real bulletins once DOE added
    more cities), so block-grouping must happen across the whole document,
    not per page. See parse_pdf().
    """
    header_positions = find_header_positions(page)
    if header_positions is None:
        return []

    bands = build_column_bands(header_positions, page.width)
    area_left, area_right = bands["AREA"]
    product_left, product_right = bands["PRODUCT"]

    words = page.extract_words(y_tolerance=WORD_Y_TOLERANCE)
    clusters = cluster_rows(words)

    row_records = []
    for c in clusters:
        area_by_line = defaultdict(list)
        for w in c["words"]:
            if area_left <= w["x0"] < area_right:
                area_by_line[round(w["top"], 1)].append(w["text"])
        area_label_candidates = [" ".join(v).strip() for v in area_by_line.values()]
        area_label_candidates = [a for a in area_label_candidates if a]

        product_words = [w["text"] for w in c["words"] if product_left <= w["x0"] < product_right]
        product = " ".join(product_words).strip()

        if product not in PRODUCT_SEQUENCE:
            continue

        buckets = defaultdict(list)
        for w in c["words"]:
            b = band_for_x(w["x0"], bands, BRAND_NAMES)
            if b:
                buckets[b].append((round(w["x0"]), w["text"]))

        brand_prices = {}
        for brand in BRAND_NAMES:
            tokens = sorted(buckets.get(brand, []))
            brand_prices[brand] = parse_price_cell(tokens)

        row_records.append({
            "area_label_candidates": area_label_candidates,
            "product": product,
            "brand_prices": brand_prices,
        })

    return row_records


def group_into_city_blocks(row_records):
    """
    Group a flat, ordered list of row records into city blocks of (up to) 7
    rows each, using the fixed PRODUCT_SEQUENCE to detect where a new city
    starts. A block that carries no usable area label (e.g. a continuation
    block split across a page boundary, with no visible label on the new
    page) inherits the previous block's city -- normal for a bulletin
    printed as one continuous table.

    Ghost label handling: the known artifact label(s) in KNOWN_GHOST_LABELS
    are only ever legitimate as the very FIRST city block in the whole
    document (that's the one real place "Caloocan City" appears at the very
    start of every bulletin checked). Every later occurrence is discarded as
    the known duplicate-text artifact, even if it's the only candidate found
    for that block -- see module docstring for how this was diagnosed.
    """
    blocks = []
    current_block = []
    for rec in row_records:
        if rec["product"] == "RON 100" and current_block:
            blocks.append(current_block)
            current_block = []
        current_block.append(rec)
    if current_block:
        blocks.append(current_block)

    parsed_rows = []
    last_known_city = None
    for block_index, block in enumerate(blocks):
        candidates = []
        for r in block:
            candidates.extend(r["area_label_candidates"])
        candidates = [c for c in candidates if c]

        if block_index != 0:
            candidates = [c for c in candidates if c not in KNOWN_GHOST_LABELS]

        city = candidates[0] if candidates else None

        if city is None:
            city = last_known_city
            if city is not None:
                logger.info("Block %d has no usable label; inheriting city '%s' from previous "
                            "block (likely split across a page boundary).", block_index, city)
        if city is None:
            logger.warning("Could not determine city for block %d; skipping block.", block_index)
            continue

        last_known_city = city
        for rec in block:
            parsed_rows.append({
                "city": city,
                "product": rec["product"],
                "brand_prices": rec["brand_prices"],
            })

    return parsed_rows


def parse_pdf(filepath, week_start):
    records = []
    with pdfplumber.open(filepath) as pdf:
        all_row_records = []
        for page in pdf.pages:
            all_row_records.extend(parse_page_rows(page))

        for row in group_into_city_blocks(all_row_records):
            for brand, (low, high, status) in row["brand_prices"].items():
                if status == "no_outlet":
                    continue
                records.append({
                    "week_start": week_start,
                    "city": row["city"],
                    "product": row["product"],
                    "brand": brand,
                    "price_low": low,
                    "price_high": high,
                    "status": status,
                })
    return records


def extract_week_start(filename):
    match = FILENAME_DATE_RE.search(filename)
    if not match:
        return None
    return f"{match.group(1)}-{match.group(2)}-{match.group(3)}"


def validate(df):
    issues = 0

    # Safety net: drop any row whose city isn't a known real NCR city.
    # This catches corrupted text (e.g. the overlapping-label artifact
    # defeating our word-separation logic on some week) regardless of
    # exactly which underlying PDF quirk caused it.
    unknown_city = df[~df["city"].isin(KNOWN_VALID_CITIES)]
    if len(unknown_city):
        bad_values = sorted(unknown_city["city"].unique())
        logger.warning("%d rows have an unrecognized city value and were dropped: %s",
                        len(unknown_city), bad_values)
        df = df.drop(unknown_city.index)
        issues += len(unknown_city)

    reported = df[df["status"] == "reported"]
    bad_prices = reported[(reported["price_low"] <= 0) | (reported["price_high"] <= 0)]
    if len(bad_prices):
        logger.warning("%d rows have non-positive prices; dropping.", len(bad_prices))
        df = df.drop(bad_prices.index)
        issues += len(bad_prices)

    inverted = df[(df["status"] == "reported") & (df["price_low"] > df["price_high"])]
    if len(inverted):
        logger.warning("%d rows have price_low > price_high; swapping.", len(inverted))
        df.loc[inverted.index, ["price_low", "price_high"]] = \
            df.loc[inverted.index, ["price_high", "price_low"]].values

    dupes = df.duplicated(subset=["week_start", "city", "product", "brand"], keep=False)
    if dupes.any():
        logger.warning("%d duplicate (week/city/product/brand) rows found.", dupes.sum())
        issues += int(dupes.sum())

    logger.info("Validation complete. %d issue(s) flagged.", issues)
    return df


def transform():
    pdf_files = sorted(glob.glob(os.path.join(RAW_DATA_DIR, "*.pdf")))
    if not pdf_files:
        logger.warning("No PDF files found in %s. Run scripts/ingest.py first.", RAW_DATA_DIR)
        return

    all_records = []
    for filepath in pdf_files:
        filename = os.path.basename(filepath)
        week_start = extract_week_start(filename)
        if week_start is None:
            logger.warning("Could not determine week_start for %s; skipping.", filename)
            continue

        try:
            records = parse_pdf(filepath, week_start)
        except Exception as exc:
            logger.error("Failed to parse %s: %s", filename, exc)
            continue

        if not records:
            logger.warning("Parsed %s: 0 rows -- investigate this file.", filename)
        else:
            logger.info("Parsed %s: %d rows", filename, len(records))
        all_records.extend(records)

    if not all_records:
        logger.warning("No records were parsed. Nothing to save.")
        return

    df = pd.DataFrame(all_records)
    df = validate(df)
    df = df.sort_values(["week_start", "city", "product", "brand"]).reset_index(drop=True)

    df.to_csv(OUTPUT_FILE, index=False)
    logger.info("Saved %d rows to %s", len(df), OUTPUT_FILE)


if __name__ == "__main__":
    os.makedirs(PROCESSED_DATA_DIR, exist_ok=True)
    transform()
    print("Transformation complete. Check data/processed/ for output.")