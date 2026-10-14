"""Driving time from the home town.

Order: table of known towns -> SQLite cache -> Nominatim (geocoding) + OSRM (routing).
Both public services are limited to 1 request/s: we respect that and cache everything.
In demo mode only the fake table of demo.py is used (no network).
"""
import logging
import re
import time

import httpx

from . import config, demo
from .db import norm

log = logging.getLogger("scout.geo")
_last_call = 0.0
COUNTRY_NAMES = {"lu": "Luxembourg", "be": "Belgique", "fr": "France"}  # Nominatim country filter


def _throttle():
    global _last_call
    wait = 1.1 - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()


def _known(city: str | None) -> int | None:
    if not city:
        return None
    key = norm(city).replace(" ", "-")
    for name, minutes in config.KNOWN_COMMUTES.items():
        if key == norm(name).replace(" ", "-") or key.startswith(norm(name).replace(" ", "-") + "-"):
            return minutes
    return None


def _route_minutes(lat: float, lon: float) -> int | None:
    _throttle()
    h = config.HOME
    r = httpx.get(f"https://router.project-osrm.org/route/v1/driving/{h['lon']},{h['lat']};{lon},{lat}",
                  params={"overview": "false"}, headers={"User-Agent": config.USER_AGENT}, timeout=20)
    if r.status_code != 200 or r.json().get("code") != "Ok":
        return None
    return round(r.json()["routes"][0]["duration"] / 60)


def _geocode(city: str, country: str | None) -> tuple[float, float] | None:
    _throttle()
    params = {"city": city, "format": "json", "limit": 1}
    if country in COUNTRY_NAMES:
        params["country"] = COUNTRY_NAMES[country]
    r = httpx.get("https://nominatim.openstreetmap.org/search", params=params,
                  headers={"User-Agent": config.USER_AGENT}, timeout=20)
    if r.status_code != 200 or not r.json():
        return None
    return float(r.json()[0]["lat"]), float(r.json()[0]["lon"])


def _city_in_text(offer: dict) -> int | None:
    """City missing (France Travail feed of EURES): first known town named in the title or the start of the text,
    e.g. "Alternance développeur web - Metz"."""
    text = norm(f"{offer.get('title', '')} {(offer.get('description') or '')[:800]}")
    hits = [(m.start(), minutes) for name, minutes in config.KNOWN_COMMUTES.items()
            if (m := re.search(rf"\b{re.escape(norm(name))}\b", text))]
    return min(hits)[1] if hits else None


def commute(con, offer: dict) -> int | None:
    """Commute in minutes, or None when the place is unknown."""
    if config.DEMO:
        return demo.DEMO_COMMUTES.get(norm(offer.get("city")))
    minutes = _known(offer.get("city"))
    if minutes is not None:
        return minutes
    lat, lon = offer.get("lat"), offer.get("lon")
    if lat is not None and lon is not None:
        query = f"@{round(lat, 2)},{round(lon, 2)}"
    elif offer.get("city"):
        query = f"{norm(offer['city'])}|{offer.get('country') or ''}"
    elif (named := _city_in_text(offer)) is not None:
        return named
    elif offer.get("country") == "lu":
        return config.KNOWN_COMMUTES.get("luxembourg")  # city not given: assume Luxembourg City
    else:
        return None
    row = con.execute("SELECT commute_min FROM geo_cache WHERE query = ?", (query,)).fetchone()
    if row:
        return row["commute_min"]
    try:
        if lat is None or lon is None:
            found = _geocode(offer["city"], offer.get("country"))
            if not found:
                con.execute("INSERT OR REPLACE INTO geo_cache VALUES (?,?,?,?)", (query, None, None, None))
                return None
            lat, lon = found
        minutes = _route_minutes(lat, lon)
    except httpx.HTTPError as e:
        log.warning("geo %s: %s", query, e)
        return None
    con.execute("INSERT OR REPLACE INTO geo_cache VALUES (?,?,?,?)", (query, lat, lon, minutes))
    return minutes
