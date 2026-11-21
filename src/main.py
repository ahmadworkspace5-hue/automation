"""AI-Powered Website Lead Generation + Automated Outreach

Usage:
  python -m src.main --location "Austin, TX" --niche "dental clinic" --max 20
  python -m src.main --location "Austin, TX" --niche "restaurant" --send --max-leads 5
  # no args -> interactive prompts for location + niche

Default is DRY-RUN: leads are analysed and emails are drafted to
data/outreach_drafts.csv — nothing is sent. Add --send to actually
send via Gmail (requires Gmail OAuth secrets, see README).
Already-contacted emails are skipped using data/sent_log.csv.

Sending limits: at most MAX_EMAILS_PER_DAY = 25 emails per day,
counted from data/sent_log.csv. Leads are always the oldest /
most outdated sites first (lowest modern score first), because
that is the whole point: businesses with old, unattractive
websites are the ones worth convincing.
"""
from __future__ import annotations

import argparse
import csv
import datetime
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.analyze import analyze_url
from src.config import Settings
from src.discover import discover
from src.extract_email import extract_emails
from src.gmail_sender import send_via_gmail_api
from src.outreach import render_email

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DATA.mkdir(exist_ok=True)


MAX_EMAILS_PER_DAY = 25


def load_sent() -> set[str]:
    p = DATA / "sent_log.csv"
    if not p.exists():
        return set()
    with p.open() as f:
        return {r["email"].strip().lower() for r in csv.DictReader(f) if r.get("email")}


def sent_today_count() -> int:
    """How many emails were already sent today (UTC date in sent_log)."""
    p = DATA / "sent_log.csv"
    if not p.exists():
        return 0
    today = datetime.date.today().isoformat()
    n = 0
    with p.open() as f:
        for r in csv.DictReader(f):
            if (r.get("date") or "").strip() == today:
                n += 1
    return n


def append_csv(path: Path, rows: list[dict], fieldnames: list[str]):
    # Only the CSV columns — lead dicts also carry score_breakdown,
    # subject, body and sent status for leads.json, and DictWriter
    # raises ValueError on any extra key (that crash killed the
    # 2026-11-21 restaurant run with exit code 1, after all 32
    # businesses had been checked and real leads found).
    rows = [{k: r.get(k, "") for k in fieldnames} for r in rows]
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        if not exists:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser(description="Find outdated business websites and outreach to them")
    ap.add_argument("--location", help="City / place, e.g. 'Austin, TX'")
    ap.add_argument("--niche", help="Business niche, e.g. 'dental clinic'")
    ap.add_argument("--max", type=int, default=20, help="Max businesses to check")
    ap.add_argument("--max-leads", type=int, default=10, help="Max leads to email/draft")
    ap.add_argument("--send", action="store_true", help="Actually send emails (default: dry-run, drafts only)")
    ap.add_argument("--threshold", type=int, default=50, help="modern_score below this = outdated")
    ap.add_argument("--businesses-csv", help="Optional CSV with name,website[,email] columns — skips discovery, useful for testing or a pre-built list")
    args = ap.parse_args()

    location = args.location or input("Enter location (city, e.g. Austin, TX): ").strip()
    niche = args.niche or input("Enter business niche (e.g. dental clinic, restaurant, hotel): ").strip()
    if not location or not niche:
        print("Location and niche are required.")
        raise SystemExit(1)

    # Daily sending cap: never more than 25 emails in one day,
    # however many leads the user asks for.
    args.max_leads = min(args.max_leads, MAX_EMAILS_PER_DAY)
    settings = Settings.from_env(location=location, niche=niche,
                                 max_businesses=args.max, max_leads=args.max_leads,
                                 dry_run=not args.send, outdated_threshold=args.threshold)
    sent = load_sent()
    sent_today = sent_today_count()
    print(f"📧 Emails already sent today: {sent_today}/{MAX_EMAILS_PER_DAY}")
    if args.businesses_csv:
        from src.discover import Business
        businesses = []
        with open(args.businesses_csv, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                if r.get("website"):
                    businesses.append(Business(name=r.get("name", r["website"]), website=r["website"],
                                               email=r.get("email", ""), source="csv"))
        print(f"\n📄 Loaded {len(businesses)} businesses from {args.businesses_csv}")
    else:
        print(f"\n🔍 Searching {niche} in {location} …")
        businesses = discover(location, niche, args.max,
                              google_places_api_key=settings.google_places_api_key)
        print(f"Found {len(businesses)} businesses with websites.")

    leads, drafts = [], []
    for i, b in enumerate(businesses, 1):
        if len(leads) >= args.max_leads:
            break
        print(f"[{i}/{len(businesses)}] {b.name} — {b.website}")
        analysis = analyze_url(b.website, threshold=args.threshold)
        print(f"    score {analysis.modern_score}/100  outdated={analysis.is_outdated}  {'; '.join(analysis.reasons[:2])}")
        if not analysis.is_outdated:
            continue
        emails = ([b.email] if getattr(b, "email", "") else []) or extract_emails(b.website)
        print(f"    emails: {emails}")
        if not emails:
            continue
        email = emails[0]
        if email in sent:
            print("    already contacted — skipping")
            continue
        subject, body = render_email(b.name, b.website, analysis.reasons,
                                     settings.sender_name, settings.sender_business,
                                     settings.sender_email, settings.sender_website, settings.sender_phone)
        lead = {"business": b.name, "website": b.website, "email": email,
                "location": location, "niche": niche,
                "modern_score": analysis.modern_score,
                "score_breakdown": analysis.breakdown,
                "issues": "; ".join(analysis.reasons),
                "positives": "; ".join(analysis.positives),
                "subject": subject, "body": body,
                "address": b.address, "phone": b.phone,
                "sent": False, "send_status": "draft"}
        leads.append(lead)
        drafts.append({"business": b.name, "email": email, "subject": subject, "body": body, "website": b.website})

        if args.send:
            if sent_today >= MAX_EMAILS_PER_DAY:
                print(f"    ⏸ daily limit reached ({MAX_EMAILS_PER_DAY}/day) — draft saved, not sent")
                lead["send_status"] = "daily limit (25/day) reached — not sent"
            else:
                try:
                    # The sending module: src/gmail_sender.py, Gmail API
                    # with an OAuth refresh token (GitHub Secrets).
                    send_via_gmail_api(email, subject, body, settings)
                    print(f"    ✅ sent to {email}")
                    append_csv(DATA / "sent_log.csv",
                               [{"email": email, "business": b.name, "website": b.website,
                                 "date": datetime.date.today().isoformat()}],
                               ["email", "business", "website", "date"])
                    sent.add(email)
                    sent_today += 1
                    lead["sent"] = True
                    lead["send_status"] = "sent"
                except Exception as e:
                    print(f"    ❌ send failed for {email}: {e}")
                    lead["send_status"] = f"send failed: {e}"
        time.sleep(settings.delay_between_sites)

    # Oldest / most outdated first — lowest score at the top.
    # That is the whole goal: old sites are the leads worth chasing.
    leads.sort(key=lambda l: l["modern_score"])
    drafts.sort(key=lambda d: next((l["modern_score"] for l in leads if l["email"] == d["email"]), 99))

    if leads:
        # CSVs must never kill the run — leads.json is the source
        # the web page reads, and it is written below regardless.
        try:
            append_csv(DATA / "leads.csv", leads,
                       ["business", "website", "email", "location", "niche", "modern_score", "issues", "address", "phone"])
            append_csv(DATA / "outreach_drafts.csv", drafts, ["business", "email", "subject", "body", "website"])
        except Exception as e:
            print(f"⚠️ Could not write CSVs ({e}) — leads.json will still be written")
    summary = {"location": location, "niche": niche, "businesses_checked": len(businesses),
               "businesses_with_website": len(businesses),
               "discovery_sources": sorted({b.source for b in businesses}),
               "leads_found": len(leads), "mode": "SEND" if args.send else "DRY-RUN",
               "daily_limit": MAX_EMAILS_PER_DAY,
               "sent_today": sent_today,
               "sent_count": sum(1 for l in leads if l.get("sent")),
               "leads": leads}
    (DATA / "last_run.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    # Public copy for the GitHub Pages web page — the workflow
    # commits this to the repo so the page can show the leads
    # without any download.
    (ROOT / "leads.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"\n✅ Done: {len(leads)} leads from {len(businesses)} businesses checked.")
    print(f"Mode: {'SEND' if args.send else 'DRY-RUN — drafts saved, nothing sent'}")
    print(f"Sent today: {sent_today}/{MAX_EMAILS_PER_DAY}")
    print(f"Files: data/leads.csv, data/outreach_drafts.csv, data/last_run.json, leads.json")


if __name__ == "__main__":
    main()
