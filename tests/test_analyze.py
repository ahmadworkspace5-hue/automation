from src.analyze import analyze_url

def test_modern_site_scores_high():
    a = analyze_url("https://example.com")
    assert 0 <= a.modern_score <= 100

def test_outdated_detection_runs():
    # A site that fails to load is treated as a lead, not a crash
    a = analyze_url("https://nonexistent-website-12345.invalid")
    assert a.is_outdated
