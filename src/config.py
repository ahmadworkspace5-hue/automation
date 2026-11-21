"""Configuration for the lead-generation pipeline.

All secrets come from environment variables / GitHub Secrets.
Never commit real credentials — see .env.example.
"""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    location: str = ""
    niche: str = ""
    max_businesses: int = 20
    max_leads: int = 10
    dry_run: bool = True
    # Outdated threshold: modern_score < this = lead
    outdated_threshold: int = 50
    # Hard cap: never send more than this many emails in one day
    max_emails_per_day: int = 25
    request_timeout: int = 15
    delay_between_sites: float = 1.0
    # Optional paid discovery (better coverage than free OSM)
    google_places_api_key: str = ""
    # Gmail API (for GitHub Actions / local sending)
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    sender_name: str = "Your Name"
    sender_business: str = "Your Web Studio"
    sender_email: str = ""
    sender_website: str = ""
    sender_phone: str = ""

    @classmethod
    def from_env(cls, **overrides) -> "Settings":
        s = cls(
            google_places_api_key=os.getenv("GOOGLE_PLACES_API_KEY", ""),
            gmail_client_id=os.getenv("GMAIL_CLIENT_ID", ""),
            gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET", ""),
            gmail_refresh_token=os.getenv("GMAIL_REFRESH_TOKEN", ""),
            sender_name=os.getenv("SENDER_NAME", "Your Name"),
            sender_business=os.getenv("SENDER_BUSINESS", "Your Web Studio"),
            sender_email=os.getenv("SENDER_EMAIL", ""),
            sender_website=os.getenv("SENDER_WEBSITE", ""),
            sender_phone=os.getenv("SENDER_PHONE", ""),
        )
        for k, v in overrides.items():
            if v is not None:
                setattr(s, k, v)
        return s
