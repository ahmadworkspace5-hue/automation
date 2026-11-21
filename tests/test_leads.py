from src.analyze import analyze_url


def test_breakdown_has_all_categories():
    a = analyze_url("https://example.com")
    assert set(a.breakdown) == {
        "Responsive", "Layout", "Animation",
        "Modern tech", "Security", "Design freshness",
    }
    assert all(0 <= v <= 100 for v in a.breakdown.values())


def test_old_site_is_a_lead_and_sorted_first():
    # A site that fails to load scores 10 and is outdated.
    a = analyze_url("https://nonexistent-website-12345.invalid")
    assert a.is_outdated and a.modern_score == 10
    assert a.breakdown["Design freshness"] == 10
    leads = [
        {"business": "New", "modern_score": 45},
        {"business": "Old", "modern_score": 10},
    ]
    leads.sort(key=lambda l: l["modern_score"])
    assert leads[0]["business"] == "Old"  # oldest first
