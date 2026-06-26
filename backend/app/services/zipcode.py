"""
ZIPcodeAPI lookup service.

Called automatically when applicant.zip or applicant.mailing_zip is saved.
Returns city, state, and county for that ZIP so they can be auto-filled
without asking the user.

County data is not included in zipcodeapi.com responses, so we use the
FCC Census Block API (free, no key) with the lat/lng returned by zipcodeapi.
"""

import logging
import httpx
from functools import lru_cache

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_API_BASE = "https://www.zipcodeapi.com/rest/{key}/info.json/{zip}/degrees"
_FCC_API  = "https://geo.fcc.gov/api/census/block/find?latitude={lat}&longitude={lng}&format=json"


@lru_cache(maxsize=512)
def _lookup_county_from_coords(lat: float, lng: float) -> str:
    """Call FCC Census Block API to get county name from lat/lng. Returns '' on failure."""
    try:
        resp = httpx.get(_FCC_API.format(lat=lat, lng=lng), timeout=5.0)
        if resp.status_code != 200:
            return ""
        data = resp.json()
        if data.get("status") != "OK":
            return ""
        county_raw = data.get("County", {}).get("name", "")
        # Strip " County" suffix so we store just "Los Angeles" not "Los Angeles County"
        return county_raw.replace(" County", "").strip() if county_raw else ""
    except Exception as exc:
        logger.warning("FCC county lookup failed for (%s, %s): %s", lat, lng, exc)
        return ""


@lru_cache(maxsize=512)
def lookup_zip(zip_code: str) -> dict | None:
    """
    Query ZIPcodeAPI for a single ZIP code, then FCC for county.
    Returns {"city": ..., "state": ..., "county": ...} or None on failure.
    Result is cached per ZIP so repeated lookups in the same process are free.
    """
    settings = get_settings()
    api_key = settings.ZIPCODE_API_KEY
    if not api_key:
        logger.warning("ZIPCODE_API_KEY not set — skipping ZIP auto-fill")
        return None

    # Strip the +4 extension if present (43215-1234 -> 43215)
    base_zip = zip_code.strip().split("-")[0]
    if len(base_zip) != 5 or not base_zip.isdigit():
        return None

    url = _API_BASE.format(key=api_key, zip=base_zip)
    try:
        resp = httpx.get(url, timeout=5.0)
        if resp.status_code != 200:
            logger.warning("ZIPcodeAPI returned %s for ZIP %s", resp.status_code, base_zip)
            return None
        data = resp.json()
        city  = data.get("city", "").strip()
        state = data.get("state", "").strip()
        if not city or not state:
            return None

        # zipcodeapi.com doesn't return county — use lat/lng + FCC to get it
        lat = data.get("lat")
        lng = data.get("lng")
        county = _lookup_county_from_coords(lat, lng) if lat and lng else ""

        return {"city": city, "state": state, "county": county}
    except Exception as exc:
        logger.warning("ZIPcodeAPI lookup failed for %s: %s", base_zip, exc)
        return None
