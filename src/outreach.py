"""Personalised outreach email generation.

Uses the analysis reasons so each email is specific, not generic spam.
Template lives in templates/email_template.txt so you can edit the
wording without touching code.
"""
from __future__ import annotations

from pathlib import Path

TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "templates" / "email_template.txt"


def render_email(business_name: str, website: str, reasons: list[str],
                 sender_name: str, sender_business: str,
                 sender_email: str = "", sender_website: str = "",
                 sender_phone: str = "") -> tuple[str, str]:
    subject = f"Quick idea for {business_name}'s website"
    top = reasons[:2]
    issues = "; ".join(top) if top else "an outdated design"
    try:
        template = TEMPLATE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        template = DEFAULT_TEMPLATE
    body = template.format(
        business_name=business_name, website=website, issues=issues,
        sender_name=sender_name, sender_business=sender_business,
        sender_email=sender_email, sender_website=sender_website,
        sender_phone=sender_phone,
    )
    return subject, body


DEFAULT_TEMPLATE = """Hello {business_name} team,

I noticed your website ({website}) has {issues}, and could benefit from a modern look.

In today's digital world, having an attractive, professional, and modern website can help attract more visitors, keep potential customers engaged, and improve your overall online presence.

If you're interested, I can create a completely modern, high-quality website for your business using the latest AI technologies, advanced animations, modern UI/UX design, and trending web development techniques — giving your business a fresh and impressive online presence.

Would you be open to a quick look at what that could look like for {business_name}? No obligation — happy to share a short preview first.

Best regards,
{sender_name}
{sender_business}
{sender_email}
{sender_website}

P.S. If this isn't relevant, just let me know and I won't follow up.
"""
