"""Send via Gmail API (OAuth refresh token) — for GitHub Actions.

Setup (once, locally):
  1. Google Cloud Console -> create OAuth client (Desktop app)
  2. Enable Gmail API, get client_id / client_secret
  3. Run scripts/get_gmail_refresh_token.py to get a refresh token
  4. Add GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET / GMAIL_REFRESH_TOKEN
     as GitHub Secrets (never commit them)

In dry-run mode nothing is sent — drafts are saved to CSV instead.
"""
from __future__ import annotations

import base64
import time
from email.message import EmailMessage


def build_message(to: str, subject: str, body: str, sender_email: str) -> dict:
    msg = EmailMessage()
    msg["To"] = to
    msg["From"] = sender_email
    msg["Subject"] = subject
    msg.set_content(body)
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def send_via_gmail_api(to: str, subject: str, body: str, settings) -> bool:
    """Send one email. Returns True on success. Requires google libs."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not all([settings.gmail_client_id, settings.gmail_client_secret, settings.gmail_refresh_token]):
        raise RuntimeError("Gmail OAuth secrets missing — set GMAIL_CLIENT_ID / SECRET / REFRESH_TOKEN")
    creds = Credentials(
        token=None,
        refresh_token=settings.gmail_refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.gmail_client_id,
        client_secret=settings.gmail_client_secret,
        scopes=["https://www.googleapis.com/auth/gmail.send"],
    )
    creds.refresh(Request())
    service = build("gmail", "v1", credentials=creds)
    payload = build_message(to, subject, body, settings.sender_email or "me")
    service.users().messages().send(userId="me", body=payload).execute()
    time.sleep(2)  # rate-limit: ~1 email / 2s, stay well under Gmail limits
    return True
