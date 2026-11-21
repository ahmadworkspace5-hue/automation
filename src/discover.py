"""Find businesses for a location + niche.

Primary (free, no key): OpenStreetMap via Nominatim (geocode) +
Overpass API (business search). Optional: Google Places API if
GOOGLE_PLACES_API_KEY is set — better coverage, especially for
restaurants / hotels / clinics.
"""
from __future__ import annotations

import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

# niche -> OSM tags to search. Add your own niches here.
NICHE_TAGS = {
    "dental clinic": [{"amenity": "dentist"}, {"healthcare": "dentist"}],
    "dentist": [{"amenity": "dentist"}, {"healthcare": "dentist"}],
    "restaurant": [{"amenity": "restaurant"}, {"amenity": "cafe"}, {"amenity": "fast_food"}],
    "hotel": [{"tourism": "hotel"}, {"tourism": "guest_house"}, {"tourism": "motel"}],
    "cafe": [{"amenity": "cafe"}, {"amenity": "restaurant"}],
    "gym": [{"leisure": "fitness_centre"}, {"amenity": "gym"}],
    "salon": [{"shop": "hairdresser"}, {"shop": "beauty"}],
    "lawyer": [{"office": "lawyer"}],
    "real estate": [{"office": "estate_agent"}],
    "plumber": [{"craft": "plumber"}],
    "electrician": [{"craft": "electrician"}],
    "pharmacy": [{"amenity": "pharmacy"}],
    "clinic": [{"amenity": "clinic"}, {"amenity": "doctors"}],
    "bakery": [{"shop": "bakery"}],
    "car repair": [{"shop": "car_repair"}, {"amenity": "car_repair"}],
}

GENERIC_TAGS = [{"amenity": "restaurant"}, {"shop": "yes"}]


@dataclass
class Business:
    name: str
    website: str = ""
    phone: str = ""
    address: str = ""
    lat: float | None = None
    lon: float | None = None
    source: str = "osm"
    email: str = ""  # publicly listed email from OSM extratags, if any


OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]


def _get_json(url: str, timeout: int = 20) -> dict:
    # Nominatim usage policy: max 1 req/sec, identify your app.
    # Set SENDER_EMAIL in .env to put a real contact address here.
    import os
    contact = os.getenv("SENDER_EMAIL", "your-email@example.com")
    time.sleep(1)
    req = urllib.request.Request(url, headers={"User-Agent": f"ai-website-lead-gen/1.0 (contact: {contact})"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "ignore"))


def geocode(location: str) -> tuple[float, float, str]:
    """Return (lat, lon, display_name) for a city / place."""
    q = urllib.parse.quote(location)
    data = _get_json(f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit=1")
    if not data:
        raise ValueError(f"Could not geocode location: {location!r}")
    return float(data[0]["lat"]), float(data[0]["lon"]), data[0].get("display_name", location)


def discover_osm(location: str, niche: str, max_businesses: int = 20, radius_m: int = 10000) -> list[Business]:
    lat, lon, display = geocode(location)
    tags = NICHE_TAGS.get(niche.strip().lower(), GENERIC_TAGS)
    # Build one Overpass query for all tag sets
    filters = []
    for t in tags:
        k, v = next(iter(t.items()))
        filters.append(f'node["{k}"="{v}"](around:{radius_m},{lat},{lon});')
        filters.append(f'way["{k}"="{v}"](around:{radius_m},{lat},{lon});')
    query = "[out:json][timeout:30];(" + "".join(filters) + ");out center 200;"
    data = None
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            req = urllib.request.Request(
                endpoint,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "ai-website-lead-gen/1.0"},
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                data = json.loads(r.read().decode("utf-8", "ignore"))
            break
        except Exception as e:  # try next mirror
            last_err = e
            continue
    if data is None:
        raise RuntimeError(f"All Overpass endpoints failed: {last_err}")

    out: list[Business] = []
    seen: set[str] = set()
    for el in data.get("elements", []):
        tags_d = el.get("tags", {})
        name = tags_d.get("name")
        website = tags_d.get("website") or tags_d.get("contact:website") or ""
        if not name:
            continue
        key = (name.lower(), website.lower())
        if key in seen:
            continue
        seen.add(key)
        # Only keep businesses with a website — that's what we analyse
        if not website:
            continue
        out.append(Business(
            name=name,
            website=website if website.startswith("http") else "https://" + website,
            phone=tags_d.get("phone") or tags_d.get("contact:phone") or "",
            address=", ".join(filter(None, [
                tags_d.get("addr:street"), tags_d.get("addr:city") or display
            ])),
            lat=el.get("lat") or (el.get("center") or {}).get("lat"),
            lon=el.get("lon") or (el.get("center") or {}).get("lon"),
            email=tags_d.get("email") or tags_d.get("contact:email") or "",
        ))
        if len(out) >= max_businesses * 2:  # fetch extra, filter later
            break
    time.sleep(1)  # be polite to the free APIs
    return out[:max_businesses * 2]


def discover_nominatim(location: str, niche: str, max_businesses: int = 20) -> list[Business]:
    """Fallback: Nominatim text search — works where Overpass is blocked.
    Returns businesses with a website listed in OSM (extratags)."""
    q = urllib.parse.quote(f"{niche} {location}")
    data = _get_json(
        f"https://nominatim.openstreetmap.org/search?q={q}&format=json&limit={max_businesses * 2}&extratags=1"
    )
    out, seen = [], set()
    for el in data:
        name = el.get("name")
        extra = el.get("extratags", {}) or {}
        website = extra.get("website") or extra.get("contact:website") or ""
        if not name or not website or name.lower() in seen:
            continue
        seen.add(name.lower())
        out.append(Business(
            name=name,
            website=website if website.startswith("http") else "https://" + website,
            phone=extra.get("phone") or extra.get("contact:phone") or "",
            address=el.get("display_name", ""),
            lat=float(el["lat"]) if el.get("lat") else None,
            lon=float(el["lon"]) if el.get("lon") else None,
            source="nominatim",
            email=extra.get("email") or extra.get("contact:email") or "",
        ))
    return out


def discover(location: str, niche: str, max_businesses: int = 20) -> list[Business]:
    """Main entry point. Overpass first, Nominatim fallback."""
    try:
        results = discover_osm(location, niche, max_businesses)
        if results:
            return results
        print("[discover] Overpass returned nothing, trying Nominatim…")
    except Exception as e:
        print(f"[discover] Overpass failed ({e}), trying Nominatim…")
    try:
        return discover_nominatim(location, niche, max_businesses)
    except Exception as e:
        print(f"[discover] Nominatim fallback failed: {e}")
        return []
