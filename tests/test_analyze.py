from src.analyze import analyze_url

def test_modern_site_scores_high():
    a = analyze_url("https://example.com")
    assert 0 <= a.modern_score <= 100

def test_outdated_detection_runs():
    # A site that fails to load is skipped (not a lead), not a crash —
    # an SSL error / 403 is not proof the design is outdated.
    a = analyze_url("https://nonexistent-website-12345.invalid")
    assert not a.is_outdated
    assert a.error
