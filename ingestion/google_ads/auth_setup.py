"""One-time OAuth helper — generates a Google Ads API refresh token.

Run once after CLIENT_ID and CLIENT_SECRET are set in .env:
    uv run python -m ingestion.google_ads.auth_setup

It opens a browser, you log in with the Google account that has access to
the Trust Ads MCC (same account Airbyte uses), and it prints a refresh token.
Paste the printed token into .env as GOOGLE_ADS_REFRESH_TOKEN.

The token only needs to be generated once — refresh tokens do not expire
unless explicitly revoked.
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/adwords"]


def main() -> int:
    client_id = os.getenv("GOOGLE_ADS_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_ADS_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        print("ERROR: GOOGLE_ADS_CLIENT_ID and GOOGLE_ADS_CLIENT_SECRET must be set in .env first.")
        return 2

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed. Run: uv sync")
        return 2

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

    flow = InstalledAppFlow.from_client_config(client_config, scopes=SCOPES)

    creds = flow.run_local_server(
        port=0,
        prompt="consent",
        access_type="offline",
        open_browser=False,
        authorization_prompt_message=(
            "\n>>> CLICK THIS URL AND LOG IN <<<\n\n{url}\n\n"
            "(Log in with the Google account that has access to the Trust Ads MCC.)\n"
        ),
        success_message="Auth complete — you can close this browser tab.",
    )

    if not creds.refresh_token:
        print("ERROR: Google did not return a refresh token. Try again with prompt=consent.")
        return 1

    print("\n" + "=" * 60)
    print("SUCCESS — paste this into .env as GOOGLE_ADS_REFRESH_TOKEN:\n")
    print(creds.refresh_token)
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
