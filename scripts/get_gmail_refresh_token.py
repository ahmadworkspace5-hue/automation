"""One-time helper: get a Gmail refresh token for GitHub Secrets.

1. Google Cloud Console -> APIs & Services -> Enable Gmail API
2. Create OAuth client ID (Desktop app), download credentials.json
   and save it next to this script.
3. Run: python scripts/get_gmail_refresh_token.py
4. Copy the printed refresh token into GitHub Secret GMAIL_REFRESH_TOKEN,
   plus client_id / client_secret from credentials.json.
"""
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.send"]

if __name__ == "__main__":
    flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
    creds = flow.run_local_server(port=0)
    print("CLIENT_ID:", creds.client_id)
    print("CLIENT_SECRET:", creds.client_secret)
    print("REFRESH_TOKEN:", creds.refresh_token)
    print("\nAdd these three as GitHub Secrets. Do NOT commit credentials.json.")
