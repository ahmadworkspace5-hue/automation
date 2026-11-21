"""Extract publicly listed business emails from a website.

Only emails visible on the site itself (homepage, /contact, /about)
or in mailto: links. No guessing, no private inboxes.
Prefers official addresses (info@ / contact@ / hello@) over
personal Gmail, but keeps Gmail if that's what the business lists.
"""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
BLOCKED = {"noreply", "no-reply", "donotreply", "webmaster", "postmaster", "example.com", "wix.com", "squarespace.com"}
IMAGE_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".pdf", ".css", ".js")

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LeadGenBot/1.0)"}


def _clean(emails: set[str]) -> list[str]:
    out = []
    for e in sorted(emails):
        e = e.lower().strip(".,;:")
        local, _, domain = e.partition("@")
        if local in BLOCKED or domain in BLOCKED or domain.endswith((".png", ".jpg")):
            continue
        if e not in out:
            out.append(e)
    return out


def _emails_from_html(html: str) -> set[str]:
    import html as html_lib
    # Search the RAW html first: emails often live in JSON-LD / scripts,
    # which BeautifulSoup's get_text() strips out.
    decoded = html_lib.unescape(html)
    found = set(EMAIL_RE.findall(decoded))
    soup = BeautifulSoup(decoded, "html.parser")
    found.update(EMAIL_RE.findall(soup.get_text(" ")))
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            found.update(EMAIL_RE.findall(html_lib.unescape(href)))
    return found


def extract_emails(website: str, timeout: int = 15) -> list[str]:
    if not website:
        return []
    base = website if website.startswith("http") else "https://" + website
    found: set[str] = set()
    paths = ["", "/contact", "/contact-us", "/about", "/about-us"]
    for p in paths:
        try:
            r = requests.get(urljoin(base, p), headers=HEADERS, timeout=timeout, allow_redirects=True)
            if r.status_code == 200 and "text/html" in r.headers.get("Content-Type", ""):
                found.update(_emails_from_html(r.text))
        except Exception:
            continue
        if found:
            # stop early once we have a good official address
            if any(e.startswith(("info@", "contact@", "hello@")) for e in found):
                break
    # Rank: official generic first, then domain email, then gmail
    def rank(e: str) -> tuple[int, str]:
        domain = urlparse(base).netloc.replace("www.", "")
        if e.startswith(("info@", "contact@", "hello@", "enquiries@", "sales@")):
            return (0, e)
        if e.endswith("@" + domain):
            return (1, e)
        if e.endswith("@gmail.com"):
            return (2, e)
        return (3, e)
    return sorted(_clean(found), key=rank)
