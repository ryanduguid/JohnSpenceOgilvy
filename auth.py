"""One-time Xero OAuth2 authorisation.

Opens the Xero consent page in your browser, catches the redirect on a local
HTTP server, exchanges the authorisation code for tokens, and saves them to
token.json. Run this once; export_tb.py refreshes tokens automatically after
that.

Prerequisite: an app at developer.xero.com with redirect URI matching
XERO_REDIRECT_URI (default http://localhost:8400/callback). The scopes
below are requested automatically at consent time; there is nothing to
configure in the developer portal.
"""

import os
import secrets
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlencode, urlparse, parse_qs

import requests
from dotenv import load_dotenv

from xero_client import save_tokens

AUTHORIZE_URL = "https://login.xero.com/identity/connect/authorize"
TOKEN_URL = "https://identity.xero.com/connect/token"
# Granular scope — required for apps created on or after 2 March 2026.
# (The old broad accounting.reports.read only works on pre-existing apps
# and retires in September 2027.)
SCOPES = "offline_access accounting.reports.trialbalance.read"


class _CallbackHandler(BaseHTTPRequestHandler):
    """Catches exactly one OAuth callback; ignores favicon and other noise."""

    def do_GET(self):  # noqa: N802 (BaseHTTPRequestHandler API)
        parsed = urlparse(self.path)
        if parsed.path != self.server.callback_path:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        self.server.auth_code = params.get("code", [None])[0]
        self.server.auth_error = params.get("error", [None])[0]
        self.server.returned_state = params.get("state", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        if self.server.auth_error:
            self.wfile.write(b"<h3>Authorisation was not completed. You can close this tab.</h3>")
        else:
            self.wfile.write(b"<h3>Authorised. You can close this tab.</h3>")

    def log_message(self, *args):  # silence request logging
        pass


def main() -> None:
    load_dotenv()
    client_id = os.environ.get("XERO_CLIENT_ID")
    client_secret = os.environ.get("XERO_CLIENT_SECRET")
    redirect_uri = os.environ.get("XERO_REDIRECT_URI", "http://localhost:8400/callback")
    if not client_id or not client_secret:
        sys.exit("Set XERO_CLIENT_ID and XERO_CLIENT_SECRET in .env (see .env.example).")

    parsed_redirect = urlparse(redirect_uri)
    state = secrets.token_urlsafe(16)

    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": SCOPES,
            "state": state,
        }
    )
    url = f"{AUTHORIZE_URL}?{query}"

    server = HTTPServer((parsed_redirect.hostname, parsed_redirect.port), _CallbackHandler)
    server.callback_path = parsed_redirect.path
    server.auth_code = None
    server.auth_error = None
    server.returned_state = None
    server.timeout = 1  # keeps Ctrl-C responsive while waiting

    if webbrowser.open(url):
        print("Opening browser for Xero consent...")
        print("If the browser did not open, paste this URL into one:")
    else:
        print("Could not open a browser (SSH or headless session?). Paste this URL into one:")
    print(f"  {url}")

    while server.auth_code is None and server.auth_error is None:
        server.handle_request()

    if server.auth_error:
        sys.exit(f"Xero returned '{server.auth_error}' — consent was denied or cancelled. Run again.")

    if server.returned_state != state:
        sys.exit("State mismatch — possible CSRF or stale callback. Run again.")

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": server.auth_code,
            "redirect_uri": redirect_uri,
        },
        auth=(client_id, client_secret),
        timeout=30,
    )
    resp.raise_for_status()
    save_tokens(resp.json())
    print("Tokens saved to token.json. Next: python export_tb.py --date 2026-06-30")


if __name__ == "__main__":
    main()
