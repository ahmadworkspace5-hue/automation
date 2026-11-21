"""Visit a website and score how modern / outdated it looks.

Heuristic, explainable scoring — no AI API needed for v1.
Score 0-100 (higher = more modern). < 50 = outdated lead.

Signals checked:
  + responsive viewport, flex/grid, CSS variables, animations,
    modern frameworks, HTTPS, semantic HTML, meta description
  - table-based layout, <font>/<center>/frames, Flash, marquee,
    heavy inline styles, no viewport, HTTP only, very old copyright
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0; +https://example.com/bot)"}


@dataclass
class Analysis:
    url: str
    modern_score: int = 0
    is_outdated: bool = False
    reasons: list[str] = field(default_factory=list)
    positives: list[str] = field(default_factory=list)
    title: str = ""
    error: str = ""
    # Per-category scores 0-100, shown on the web page so a lead's
    # owner can see exactly what is old: mobile, layout, animation,
    # modern tech, security, and overall design freshness.
    breakdown: dict[str, int] = field(default_factory=dict)


def fetch(url: str, timeout: int = 15) -> tuple[str, str]:
    r = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r.text, r.url


def analyze_url(url: str, timeout: int = 15, threshold: int = 50) -> Analysis:
    a = Analysis(url=url)
    try:
        html, final_url = fetch(url, timeout)
        a.url = final_url
    except Exception as e:
        # A site that does not load (SSL error, 403, timeout) is NOT
        # proof it is outdated — many modern sites block bots or
        # have a broken certificate. Treat it as unscorable and
        # skip it, instead of calling it a lead with score 10.
        # (The 2026-11-21 restaurant run scored several such sites
        # 10/100 and listed them as outdated, which was misleading.)
        a.error = str(e)[:200]
        a.reasons.append(f"Website did not load reliably ({a.error}) — skipped, not scored as outdated")
        a.modern_score = 10
        a.is_outdated = False
        a.breakdown = {"Responsive": 0, "Layout": 0, "Animation": 0,
                       "Modern tech": 0, "Security": 0, "Design freshness": 10}
        return a

    soup = BeautifulSoup(html, "html.parser")
    a.title = (soup.title.string.strip() if soup.title and soup.title.string else "")
    text = html.lower()
    css = " ".join(
        (tag.get_text() if hasattr(tag, "get_text") else "")
        for tag in soup.find_all("style")
    ).lower()
    # also inline style attributes
    inline = " ".join(tag.get("style", "") for tag in soup.find_all(style=True)).lower()

    score = 20  # base: it loads
    # --- positives ---
    if soup.find("meta", attrs={"name": "viewport"}):
        score += 12; a.positives.append("Mobile-responsive (viewport meta)")
    if re.search(r"display\s*:\s*(flex|grid)", css + inline):
        score += 10; a.positives.append("Modern layout (Flexbox / Grid)")
    if "--" in css and "var(" in css:
        score += 6; a.positives.append("Modern CSS variables")
    if re.search(r"@(media|keyframes)|animation\s*:|transition\s*:", css):
        score += 10; a.positives.append("Animations / responsive breakpoints")
    if re.search(r"tailwind|bootstrap\s*5|react|vue|next\.js|nuxt|angular", text):
        score += 8; a.positives.append("Modern framework / CSS system detected")
    if a.url.startswith("https://"):
        score += 6; a.positives.append("Secure HTTPS")
    if soup.find("meta", attrs={"name": "description"}):
        score += 4; a.positives.append("SEO meta description")
    if soup.find_all(["header", "nav", "main", "footer", "section"]):
        score += 4; a.positives.append("Semantic HTML structure")

    # --- outdated signals ---
    if soup.find("table") and len(soup.find_all("table")) >= 2:
        score -= 12; a.reasons.append("Table-based layout (old-fashioned design)")
    if soup.find(["font", "center", "marquee", "frame", "frameset"]) or "flash" in text:
        score -= 12; a.reasons.append("Very old HTML tags / Flash-era elements")
    if len(inline) > 2000:
        score -= 8; a.reasons.append("Heavy inline styling, no modern stylesheet structure")
    if not soup.find("meta", attrs={"name": "viewport"}):
        score -= 10; a.reasons.append("Not mobile-responsive")
    if a.url.startswith("http://"):
        score -= 6; a.reasons.append("No HTTPS")
    if not re.search(r"@(media|keyframes)|animation\s*:|transition\s*:", css):
        score -= 6; a.reasons.append("No modern animations or transitions")
    m = re.search(r"©[^0-9]*((?:19|20)\d{2})", html)
    if m and int(m.group(1)) < 2018:
        score -= 5; a.reasons.append(f"Copyright still shows {m.group(1)} — site looks unmaintained")
    if not a.positives:
        a.reasons.append("No modern design signals found")

    a.modern_score = max(0, min(100, score))
    a.is_outdated = a.modern_score < threshold
    if a.is_outdated and not a.reasons:
        a.reasons.append("Overall design scores as outdated")

    # --- per-category breakdown (0-100 each) ---
    has_viewport = bool(soup.find("meta", attrs={"name": "viewport"}))
    has_media = bool(re.search(r"@media", css))
    has_anim = bool(re.search(r"@keyframes|animation\s*:|transition\s*:", css))
    has_flex = bool(re.search(r"display\s*:\s*(flex|grid)", css + inline))
    has_framework = bool(re.search(r"tailwind|bootstrap\s*5|react|vue|next\.js|nuxt|angular", text))
    old_penalties = 0
    if soup.find("table") and len(soup.find_all("table")) >= 2:
        old_penalties += 30
    if soup.find(["font", "center", "marquee", "frame", "frameset"]) or "flash" in text:
        old_penalties += 30
    if len(inline) > 2000:
        old_penalties += 20
    if m and int(m.group(1)) < 2018:
        old_penalties += 20
    a.breakdown = {
        "Responsive": 100 if (has_viewport and has_media) else (70 if has_viewport else 0),
        "Layout": 100 if has_flex else (40 if soup.find_all(["header", "nav", "main", "footer", "section"]) else 0),
        "Animation": 100 if has_anim else 0,
        "Modern tech": 100 if has_framework else (50 if ("--" in css and "var(" in css) else 0),
        "Security": 100 if a.url.startswith("https://") else 0,
        "Design freshness": max(0, 100 - old_penalties),
    }
    return a
