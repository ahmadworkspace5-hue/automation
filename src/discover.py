"""Find businesses for a location + niche.

Discovery sources, in order (first one that returns results wins,
with the others merged in when they add new names):

1. Google Places API (new) — best coverage, especially outside
   the US/EU, e.g. clinics in Lahore. Needs GOOGLE_PLACES_API_KEY
   (free tier: $200/month credit from Google, Text Search is
   ~$0.032 per call). Set it as a GitHub Secret / in .env.
2. OpenStreetMap via Overpass — free, no key. Wider tag set and a
   25 km radius (was 10 km), because a big city centre is not
   where most clinics are.
3. Nominatim text search — free fallback, several query variants.
4. Web search — for businesses OSM knows by name but with no
   website listed, look up their website with DuckDuckGo (free,
   no key). Only an own-domain result counts; Facebook / directory
   listings are skipped, because we need a real website to analyse.
   If OSM still yields almost nothing, web search is also used
   directly ("clinic in Lahore") to find businesses from their
   own websites — this is what rescues cities where OSM is thin.

Diagnosis (Nov 2026): the first live run — "Clinic" in Lahore,
max 30 — found only 1 business with a website. That was not a
crash: OpenStreetMap in Lahore simply lists almost no clinic
websites (1 in a 10 km radius). The old code only kept businesses
that already had a website in OSM, used a narrow tag set
(amenity=clinic / doctors only) and a 10 km radius, and the
Google Places key advertised in the README was never actually
used. All three gaps are fixed here.
"""
from __future__ import annotations

import html as html_lib
import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass

# niche -> OSM tags to search. Add your own niches here.
NICHE_TAGS = {
    "dental clinic": [
        {"amenity": "dentist"}, {"healthcare": "dentist"},
        {"amenity": "clinic"}, {"healthcare": "clinic"},
    ],
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
    # Clinic: OSM uses several overlapping tags for the same thing.
    # A clinic in Lahore is as likely to be tagged healthcare=clinic,
    # amenity=doctors, healthcare=doctor or amenity=hospital as
    # amenity=clinic, so search all of them.
    "clinic": [
        {"amenity": "clinic"}, {"amenity": "doctors"},
        {"healthcare": "clinic"}, {"healthcare": "doctor"},
        {"healthcare": "centre"}, {"amenity": "hospital"},
        {"healthcare": "hospital"}, {"amenity": "dentist"},
    ],
    "hospital": [{"amenity": "hospital"}, {"healthcare": "hospital"}],
    "bakery": [{"shop": "bakery"}],
    "car repair": [{"shop": "car_repair"}, {"amenity": "car_repair"}],
}

GENERIC_TAGS = [{"amenity": "restaurant"}, {"shop": "yes"}]

# Big cities need a bigger search circle than 10 km.
DEFAULT_RADIUS_M = 25000

# Domains that are not a business's own website — skip them when
# resolving a website from a web search.
SKIP_DOMAINS = (
    "duckduckgo.com", "google.", "bing.com", "facebook.com",
    "instagram.com", "youtube.com", "twitter.com", "x.com",
    "linkedin.com", "wikipedia.org", "wikidata.org",
    "yelp.", "tripadvisor.", "trustpilot.", "justdial.",
    "yellowpages.", "hotfrog.", "find-us-here.", "cylex.",
    "pakistan-places.", "hamariweb.", "urdupoint.",
    # Aggregator / directory sites — they list clinics, they are
    # not a clinic themselves. Analysing them finds no lead.
    "marham.pk", "oladoc.com", "instacare.pk", "whatclinic.com",
    "citysearch.pk", "on-mend.com", "findclinic.pk",
    "gamcapakistan.pk", "practo.com", "zocdoc.com", "healthgrades.",
)

# Web-search result titles that are list / directory pages, not
# one business: "List of Clinics in Lahore", "Best Hospitals…".
SKIP_TITLE_PHRASES = (
    "list of", "clinics in", "hospitals in", "doctors in",
    "best ", "top 10", "check prices", "reviews",
)


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


def _norm_website(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith("http"):
        url = "https://" + url
    return url


def discover_google_places(location: str, niche: str, max_businesses: int = 20,
                           api_key: str = "") -> list[Business]:
    """Google Places API (new) Text Search. Returns [] if no key.

    Docs: https://developers.google.com/maps/documentation/places/web-service/text-search
    """
    if not api_key:
        return []
    url = "https://places.googleapis.com/v1/places:searchText"
    payload = json.dumps({
        "textQuery": f"{niche} in {location}",
        "maxResultCount": min(max_businesses, 20),
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": "places.displayName,places.websiteUri,places.formattedAddress,places.internationalPhoneNumber,places.location",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.loads(r.read().decode("utf-8", "ignore"))
    out: list[Business] = []
    for p in data.get("places", []) or []:
        name = (p.get("displayName") or {}).get("text", "")
        website = p.get("websiteUri", "")
        if not name or not website:
            continue
        loc = p.get("location") or {}
        out.append(Business(
            name=name, website=_norm_website(website),
            phone=p.get("internationalPhoneNumber", ""),
            address=p.get("formattedAddress", ""),
            lat=loc.get("latitude"), lon=loc.get("longitude"),
            source="google_places",
        ))
    return out


def discover_osm(location: str, niche: str, max_businesses: int = 20,
                 radius_m: int = DEFAULT_RADIUS_M) -> list[Business]:
    """Overpass search. Returns businesses WITH a website AND, in
    `source` order, named businesses without one (website="") so the
    caller can try to resolve their website by web search."""
    lat, lon, display = geocode(location)
    tags = NICHE_TAGS.get(niche.strip().lower(), GENERIC_TAGS)
    filters = []
    for t in tags:
        k, v = next(iter(t.items()))
        filters.append(f'node["{k}"="{v}"](around:{radius_m},{lat},{lon});')
        filters.append(f'way["{k}"="{v}"](around:{radius_m},{lat},{lon});')
    query = "[out:json][timeout:30];(" + "".join(filters) + ");out center 1000;"
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
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(Business(
            name=name,
            website=_norm_website(website),
            phone=tags_d.get("phone") or tags_d.get("contact:phone") or "",
            address=", ".join(filter(None, [
                tags_d.get("addr:street"), tags_d.get("addr:city") or display
            ])),
            lat=el.get("lat") or (el.get("center") or {}).get("lat"),
            lon=el.get("lon") or (el.get("center") or {}).get("lon"),
            email=tags_d.get("email") or tags_d.get("contact:email") or "",
        ))
    # Websites first, then named businesses without a website.
    out.sort(key=lambda b: 0 if b.website else 1)
    time.sleep(1)  # be polite to the free APIs
    return out


def discover_nominatim(location: str, niche: str, max_businesses: int = 20) -> list[Business]:
    """Fallback: Nominatim text search, several query variants.
    Returns businesses with a website listed in OSM (extratags),
    plus named ones without a website for web-search resolution."""
    queries = [f"{niche} {location}", f"{niche}s in {location}", f"{location} {niche}"]
    out, seen = [], set()
    for q in queries:
        try:
            data = _get_json(
                "https://nominatim.openstreetmap.org/search?q="
                + urllib.parse.quote(q)
                + f"&format=json&limit={max_businesses * 2}&extratags=1"
            )
        except Exception:
            continue
        for el in data:
            name = el.get("name")
            if not name or name.lower() in seen:
                continue
            seen.add(name.lower())
            extra = el.get("extratags", {}) or {}
            website = extra.get("website") or extra.get("contact:website") or ""
            out.append(Business(
                name=name,
                website=_norm_website(website),
                phone=extra.get("phone") or extra.get("contact:phone") or "",
                address=el.get("display_name", ""),
                lat=float(el["lat"]) if el.get("lat") else None,
                lon=float(el["lon"]) if el.get("lon") else None,
                source="nominatim",
                email=extra.get("email") or extra.get("contact:email") or "",
            ))
        if len(out) >= max_businesses:
            break
    out.sort(key=lambda b: 0 if b.website else 1)
    return out


def _duckduckgo_results(query: str) -> list[tuple[str, str]]:
    """DuckDuckGo HTML search (free, no key). Returns
    [(title, url), ...] in result order."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"})
        with urllib.request.urlopen(req, timeout=15) as r:
            page = r.read().decode("utf-8", "ignore")
    except Exception:
        return []
    out: list[tuple[str, str]] = []
    # Result links look like <a class="result__a" href="...">Title</a>
    for href, title in re.findall(r'result__a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', page, re.S):
        href = html_lib.unescape(href)
        m = re.search(r"[?&]uddg=([^&]+)", href)
        if m:
            href = urllib.parse.unquote(m.group(1))
        title = re.sub(r"<[^>]+>", "", html_lib.unescape(title)).strip()
        if href.startswith("http") and title:
            out.append((title, href))
    return out


def _is_own_domain(url: str) -> bool:
    try:
        host = urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return False
    if not host:
        return False
    return not any(host.endswith(d) or d in host for d in SKIP_DOMAINS)


def find_website_via_search(name: str, location: str) -> str:
    """Find a business's own website with a DuckDuckGo search
    (free, no key). Returns "" when nothing suitable is found."""
    for title, href in _duckduckgo_results(f"{name} {location} official website"):
        if _is_own_domain(href):
            return href
    return ""


def discover_via_web_search(location: str, niche: str, max_businesses: int = 20) -> list[Business]:
    """Find businesses straight from web search results — the
    source that works when OSM has almost nothing (e.g. clinics
    in Lahore). Each result's own-domain website becomes a
    business; the business name is the result title, cleaned up."""
    queries = [
        f"{niche} in {location}",
        f"best {niche} {location}",
        f"{niche} {location} Pakistan",
        f"private {niche} {location}",
    ]
    out, seen_hosts = [], set()
    for q in queries:
        for title, href in _duckduckgo_results(q):
            if not _is_own_domain(href):
                continue
            host = urllib.parse.urlparse(href).netloc.lower()
            if host in seen_hosts:
                continue
            seen_hosts.add(host)
            # Homepage only — a deep link is not the business site.
            parsed = urllib.parse.urlparse(href)
            website = f"{parsed.scheme}://{parsed.netloc}/"
            # Skip list / directory pages, not one business.
            if any(p in title.lower() for p in SKIP_TITLE_PHRASES):
                continue
            # Name: title up to a separator, e.g. "X Clinic | Lahore"
            name = re.split(r"\s*[|\-–—]\s*", title)[0].strip()
            name = re.sub(r"\s+", " ", name)
            if not name or len(name) < 3:
                continue
            out.append(Business(name=name, website=website, source="websearch"))
            if len(out) >= max_businesses:
                return out
        time.sleep(1)
    return out


def _merge(base: list[Business], extra: list[Business]) -> list[Business]:
    seen = {b.name.lower() for b in base}
    for b in extra:
        if b.name.lower() in seen:
            continue
        seen.add(b.name.lower())
        base.append(b)
    return base


def discover(location: str, niche: str, max_businesses: int = 20,
             google_places_api_key: str = "") -> list[Business]:
    """Main entry point. Google Places first (if key), then OSM
    Overpass, then Nominatim, then web search to fill in missing
    websites. Only businesses with a website are returned — that
    is what the analyser needs."""
    all_found: list[Business] = []

    if google_places_api_key:
        try:
            gp = discover_google_places(location, niche, max_businesses, google_places_api_key)
            print(f"[discover] Google Places: {len(gp)} businesses with websites")
            all_found = _merge(all_found, gp)
        except Exception as e:
            print(f"[discover] Google Places failed ({e}), falling back to OSM…")

    try:
        osm = discover_osm(location, niche, max_businesses)
        print(f"[discover] Overpass: {len(osm)} businesses "
              f"({sum(1 for b in osm if b.website)} with a website)")
        all_found = _merge(all_found, osm)
    except Exception as e:
        print(f"[discover] Overpass failed ({e}), trying Nominatim…")

    if not any(b.website for b in all_found):
        try:
            nom = discover_nominatim(location, niche, max_businesses)
            print(f"[discover] Nominatim: {len(nom)} businesses "
                  f"({sum(1 for b in nom if b.website)} with a website)")
            all_found = _merge(all_found, nom)
        except Exception as e:
            print(f"[discover] Nominatim fallback failed: {e}")

    with_website = [b for b in all_found if b.website]
    if len(with_website) >= max_businesses:
        return with_website[:max_businesses]

    # Fill the gap: resolve websites for named businesses that
    # OSM/Nominatim knew by name only (at most a few searches,
    # so a run stays fast and polite).
    no_website = [b for b in all_found if not b.website]
    print(f"[discover] Resolving websites by web search for {min(len(no_website), 10)} businesses…")
    for b in no_website[:10]:
        found = find_website_via_search(b.name, location)
        if found:
            b.website = found
            b.source = b.source + "+websearch"
            with_website.append(b)
            print(f"[discover]   {b.name} -> {found}")
        time.sleep(1)
        if len(with_website) >= max_businesses:
            break

    # Still short (e.g. OSM has almost nothing in this city)?
    # Find businesses straight from web search results.
    if len(with_website) < max_businesses:
        try:
            web = discover_via_web_search(location, niche, max_businesses)
            print(f"[discover] Web search: {len(web)} businesses with websites")
            for b in web:
                if b.website not in {x.website for x in with_website}:
                    with_website.append(b)
                if len(with_website) >= max_businesses:
                    break
        except Exception as e:
            print(f"[discover] Web search failed: {e}")
    print(f"[discover] Total with a website: {len(with_website)}")
    return with_website[:max_businesses]
