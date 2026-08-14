"""
Phase 2 — Data Ingestion

Downloads weekly "NCR Price Monitoring" fuel price bulletins (PDF) published
by the Philippine Department of Energy (DOE), Oil Industry Management Bureau.

Source: https://prod-cms.doe.gov.ph/documents/d/guest/ncr-price-monitoring-{MMDDYYYY}-pdf
Cadence: weekly (bulletins are usually dated on a Monday/Tuesday each week)

Notes:
- robots.txt on doe.gov.ph does not disallow this content path.
- We intentionally start with a SMALL, recent date range so the script is
  fast and reliable to run/grade. Historical backfill can be expanded later
  by widening START_DATE.
- A single missing/renamed week (DOE occasionally shifts the publish day)
  should not crash the whole run — failures are logged and skipped.
"""

import os
import time
import logging
from datetime import date, timedelta

import requests

RAW_DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

# DOE publishes these on a rolling weekly basis. Adjust as needed.
START_DATE = date(2025, 7, 1)   # small, recent range for a fast, reliable first run
END_DATE = date.today()
STEP_DAYS = 7

URL_TEMPLATE = "https://prod-cms.doe.gov.ph/documents/d/guest/ncr-price-monitoring-{}-pdf"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DEP-Learning-Project/1.0; "
        "+https://github.com/) fuel-price-pipeline-student-project"
    )
}

REQUEST_DELAY_SECONDS = 1.5  # be a polite, low-frequency client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def build_candidate_dates(start: date, end: date, step_days: int):
    """Yield candidate bulletin dates from start to end, step_days apart."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=step_days)


def fetch_bulletin(bulletin_date: date) -> bytes | None:
    """
    Attempt to download the PDF for a given bulletin date.
    Returns the raw PDF bytes on success, or None if not found / failed.
    """
    date_str = bulletin_date.strftime("%m%d%Y")
    url = URL_TEMPLATE.format(date_str)

    try:
        response = requests.get(url, headers=HEADERS, timeout=15)
    except requests.RequestException as exc:
        logger.warning("Request error for %s (%s): %s", bulletin_date, url, exc)
        return None

    if response.status_code == 200 and response.content:
        content_type = response.headers.get("Content-Type", "")
        if "pdf" in content_type.lower() or response.content[:4] == b"%PDF":
            return response.content
        logger.warning(
            "Unexpected content type for %s: %s (skipping)",
            bulletin_date, content_type,
        )
        return None

    logger.info(
        "No bulletin found for %s (status %s) — DOE may not have published "
        "on this exact date, or the URL pattern shifted that week.",
        bulletin_date, response.status_code,
    )
    return None


def save_raw_pdf(bulletin_date: date, content: bytes) -> str:
    """Save raw PDF bytes to data/raw/ with a clear, sortable filename."""
    filename = f"ncr_price_monitoring_{bulletin_date.isoformat()}.pdf"
    filepath = os.path.join(RAW_DATA_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath


def ingest():
    candidate_dates = list(build_candidate_dates(START_DATE, END_DATE, STEP_DAYS))
    logger.info(
        "Attempting to fetch %d weekly bulletin(s) from %s to %s",
        len(candidate_dates), START_DATE, END_DATE,
    )

    successes, failures = 0, 0

    for bulletin_date in candidate_dates:
        content = fetch_bulletin(bulletin_date)

        if content is not None:
            filepath = save_raw_pdf(bulletin_date, content)
            logger.info("Saved: %s", filepath)
            successes += 1
        else:
            failures += 1

        time.sleep(REQUEST_DELAY_SECONDS)

    logger.info(
        "Ingestion finished. %d succeeded, %d failed/skipped out of %d attempted.",
        successes, failures, len(candidate_dates),
    )

    if successes == 0:
        logger.warning(
            "No bulletins were downloaded. Check that the URL pattern or date "
            "range is still valid — DOE occasionally changes its publish "
            "schedule or URL slug format."
        )


if __name__ == "__main__":
    os.makedirs(RAW_DATA_DIR, exist_ok=True)
    ingest()
    print("Ingestion complete. Check data/raw/ for output.")