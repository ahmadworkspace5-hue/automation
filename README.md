# AI-Powered Website Lead Generation & Automated Outreach

Enter a **location + business niche** — the system does the rest:

1. Search for businesses in that location / niche
2. Find their websites
3. Visit & analyse each website
4. Identify outdated, boring, traditionally-designed sites
5. Find publicly listed business emails
6. Generate a short, personalised outreach email
7. Send it via your connected Gmail — or save it as a draft first

> **Default is dry-run.** Nothing is sent unless you add `--send`
> (locally) or uncheck *dry-run* in GitHub Actions. Review
> `data/outreach_drafts.csv` before sending.

## How it works

```
location + niche
      ↓
src/discover.py   — Google Places API first (if GOOGLE_PLACES_API_KEY
                    is set — best coverage, esp. outside US/EU),
                    then OpenStreetMap Overpass (25 km radius, wide
                    tag set), then Nominatim, then a web search to
                    find websites for businesses OSM knows by name
                    only. Free OSM alone is thin in places like
                    Lahore: the first live run ("Clinic", Lahore)
                    found only 1 clinic with a listed website.
      ↓
src/analyze.py    — fetches each site, scores 0–100 for modernity
                    viewport, Flexbox/Grid, CSS variables, animations,
                    frameworks, HTTPS, semantic HTML  (+)
                    table layout, <font>/frames, Flash, no viewport,
                    HTTP only, old copyright  (−)
                    Score < 50 = outdated lead
      ↓
src/extract_email.py — scrapes homepage + /contact + /about for
                    publicly listed emails / mailto: links only.
                    Prefers info@ / contact@ / hello@, then domain
                    email, then Gmail if that's what they list.
      ↓
src/outreach.py   — personalised email from templates/email_template.txt,
                    naming the specific issues found on their site
      ↓
src/gmail_sender.py — Gmail API (OAuth refresh token) or dry-run CSV
      ↓
data/leads.csv, data/outreach_drafts.csv, data/last_run.json
```

## Quick start — local

```bash
git clone <your-repo-url>
cd ai-website-lead-generation
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your sender details

# Interactive — it will ask for location + niche
python -m src.main

# Or one command, dry-run (safe default)
python -m src.main --location "Austin, TX" --niche "dental clinic" --max 20

# Actually send (needs Gmail OAuth, see below)
python -m src.main --location "Austin, TX" --niche "restaurant" --max-leads 5 --send

# Test without discovery (uses a CSV list instead)
python -m src.main --location "Austin, TX" --niche "dental clinic" \
  --businesses-csv data/sample_businesses.csv --threshold 80
```

> **Tested locally (Nov 2026):** analysis, email extraction and draft
> generation all work — e.g. Austin Emergency Dental scored 72/100,
> its publicly listed `admin@emergencydentalaustin.com` was found
> (in JSON-LD, not just visible text), and a personalised draft was
> saved to `data/outreach_drafts.csv` in dry-run mode, nothing sent.
> One caveat found in testing: OpenStreetMap (Nominatim / Overpass)
> rate-limits shared IPs and returned 403 in this sandbox, so the
> live discovery run returned 0 businesses here. It should work
> from GitHub Actions, and the code now tries 3 Overpass mirrors
> then falls back to Nominatim. For reliable discovery, add a
> Google Places API key (`GOOGLE_PLACES_API_KEY`) — see `src/discover.py`.
>
> **First live GitHub run (Nov 2026):** "Clinic" in Lahore, max 30 —
> the pipeline ran, but found only 1 business with a website and
> 0 leads. OSM in Lahore lists almost no clinic websites. Discovery
> was then fixed: Google Places is now actually used when a key is
> set (it was advertised but not implemented), OSM radius went
> 10 km → 25 km with a wider clinic tag set, and businesses OSM
> knows by name only now get their website looked up by web search.

Supported niches out of the box: dental clinic, dentist, restaurant,
hotel, cafe, gym, salon, lawyer, real estate, plumber, electrician,
pharmacy, clinic, bakery, car repair. Add more in `src/discover.py`
(`NICHE_TAGS`).

## Quick start — GitHub Actions (no computer needed)

1. Push this repo to GitHub.
2. Go to **Actions → Lead Outreach → Run workflow**.
3. Enter `location`, `niche`, `max_businesses`, `max_leads`.
4. Leave **dry_run = true** the first time — download the
   `leads-…` artifact and review the drafts.
5. Run again with dry-run off to send.

The workflow is `.github/workflows/lead-outreach.yml`.
Results are uploaded as an artifact (`data/leads.csv`,
`data/outreach_drafts.csv`, `data/last_run.json`).

## Better discovery — Google Places (recommended)

Free OpenStreetMap is thin in many cities. With a Google Places
API key, discovery finds far more businesses with real websites.

1. Google Cloud Console → enable **Places API (New)**
2. Create an API key (restrict it to Places API)
3. Add it as a **GitHub Secret** named `GOOGLE_PLACES_API_KEY`
   (repo → Settings → Secrets → Actions), or in `.env` locally.
4. Run the workflow again — no code change needed. If the key is
   missing, the system falls back to OpenStreetMap + web search.

## The web page — leads shown, no download

`index.html` (GitHub Pages) is the control panel: pick a city, niche,
limits and dry-run, press Run, and the leads appear on the page itself
— business, website, public email, overall score (lowest = oldest
first), and a per-category breakdown (Responsive, Layout, Animation,
Modern tech, Security, Design freshness) plus the exact issues and
the draft email. The workflow publishes `leads.json` to the repo
after each run, and the page reads it. No file download is needed.

## Sending emails — where the module is, and the 25/day limit

The sending module is **`src/gmail_sender.py`**. It is called from
`src/main.py` only when a run is *not* a dry-run (`--send` locally,
or dry-run off in GitHub Actions / on the web page). It sends one
personalised email per lead through the **Gmail API** using an
OAuth refresh token.

**Daily limit: 25 emails per day, hard cap.** `src/main.py` counts
today's sends in `data/sent_log.csv` and stops sending at 25 —
drafts are still saved, nothing extra goes out. The web page's
max-leads slider also stops at 25.

**Why connecting Gmail to Muse is not enough:** that connection
lets *me* read/send in this chat. GitHub Actions runs on GitHub's
servers, on its own — it needs its own Gmail API login, stored as
GitHub Secrets. That is a one-time setup:

1. Google Cloud Console → enable **Gmail API**
2. Create an OAuth client (Desktop app) → download `credentials.json`
3. `python scripts/get_gmail_refresh_token.py` → copy the refresh token
4. Add as **GitHub Secrets** (repo → Settings → Secrets → Actions):
   `GMAIL_CLIENT_ID`, `GMAIL_CLIENT_SECRET`, `GMAIL_REFRESH_TOKEN`,
   plus `SENDER_NAME`, `SENDER_BUSINESS`, `SENDER_EMAIL`, `SENDER_WEBSITE`
5. Locally, put the same values in `.env` (never commit it).

Until those secrets are set, sending fails safely — the run still
finds the leads and saves the drafts, and nothing is sent.

## The outreach message

Edit `templates/email_template.txt` — the wording you gave is the
default, personalised with the business name, their website, and the
specific issues found (e.g. “Table-based layout; Not mobile-responsive”).

Subject: `Quick idea for {business_name}'s website`

## Safety, dedup & compliance — read this

This tool only contacts **businesses that publicly list an email
on their own website**, and every email includes an opt-out line
(“If this isn't relevant, just let me know and I won't follow up”).

- **Dry-run first, always.** Review drafts before any send.
- **Dedup:** `data/sent_log.csv` skips anyone already contacted.
- **Rate-limited:** ~1 email / 2 seconds in the sender, max 10 leads
  by default. Don't raise this aggressively — Gmail will throttle you.
- **Respect the law in the recipient's country:** B2B cold email is
  regulated differently in the US (CAN-SPAM), EU/UK (GDPR/PECR —
  generally needs a lawful basis and an easy opt-out), Canada (CASL),
  and elsewhere. Only email businesses where you have a lawful basis,
  keep an opt-out list, and stop contacting anyone who opts out.
- **Don't scrape private / personal emails**, don't guess addresses,
  and don't add people to a newsletter — this is one-to-one outreach only.
- The discovery APIs (Nominatim / Overpass) are free shared services:
  the code sleeps between requests. Don't hammer them.

## Project structure

```
├── src/
│   ├── main.py            # CLI + pipeline orchestration
│   ├── config.py          # Settings from env / GitHub Secrets
│   ├── discover.py        # OSM / Google Places business search
│   ├── analyze.py         # Website modernity scoring
│   ├── extract_email.py   # Public email extraction
│   ├── outreach.py        # Email template rendering
│   └── gmail_sender.py    # Gmail API sending
├── templates/email_template.txt
├── .github/workflows/lead-outreach.yml
├── scripts/get_gmail_refresh_token.py
├── tests/test_analyze.py
└── data/                  # leads.csv, outreach_drafts.csv, last_run.json
```

## Roadmap ideas

- AI scoring with an LLM (screenshot + design critique) instead of heuristics
- Google Places as the default discovery source
- A review queue (approve drafts in GitHub before sending)
- Follow-up sequence (1 polite follow-up, then stop)
- CRM export (HubSpot / Sheets)
