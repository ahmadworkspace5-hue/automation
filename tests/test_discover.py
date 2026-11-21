from src.discover import (
    NICHE_TAGS,
    _merge,
    _norm_website,
    discover_google_places,
    Business,
)


def test_clinic_tags_cover_osm_variants():
    tags = NICHE_TAGS["clinic"]
    flat = {(k, v) for t in tags for k, v in t.items()}
    assert ("amenity", "clinic") in flat
    assert ("healthcare", "clinic") in flat
    assert ("amenity", "doctors") in flat
    assert ("healthcare", "doctor") in flat
    assert ("amenity", "hospital") in flat


def test_norm_website_adds_scheme():
    assert _norm_website("example.com") == "https://example.com"
    assert _norm_website("https://example.com") == "https://example.com"
    assert _norm_website("") == ""


def test_merge_dedupes_by_name():
    base = [Business(name="A Clinic", website="https://a.example")]
    merged = _merge(base, [Business(name="a clinic", website="https://a2.example"),
                           Business(name="B Clinic", website="https://b.example")])
    assert [b.name for b in merged] == ["A Clinic", "B Clinic"]


def test_google_places_without_key_returns_empty():
    assert discover_google_places("Lahore", "Clinic", 5, api_key="") == []
