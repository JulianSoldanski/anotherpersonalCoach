"""
Einmaliger OAuth-Setup: Browser öffnen, Strava erlauben, redirect-URL oder code einfügen.
Ergebnis: access_token + refresh_token — REFRESH_TOKEN in .env übernehmen.

In der Strava-App (https://www.strava.com/settings/api) muss "Authorization Callback Domain"
bzw. die Redirect-URL zu STRAVA_REDIRECT_URI passen (z. B. localhost).
"""
import os
import sys
from urllib.parse import parse_qs, urlencode, urlparse

import requests
from dotenv import load_dotenv

load_dotenv()

AUTH_URL = "https://www.strava.com/oauth/authorize"
# Offizieller Endpunkt laut Strava-Doku (nicht nur /oauth/token)
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"


def extract_code(user_input: str) -> str:
    s = user_input.strip()
    if not s:
        return ""
    if "code=" in s:
        if not s.startswith("http"):
            prefix = "http://localhost" if s.startswith("?") else "http://localhost/"
            s = prefix + s.lstrip("/")
        qs = parse_qs(urlparse(s).query)
        codes = qs.get("code", [])
        if codes:
            return codes[0].strip()
    return s


def main() -> None:
    client_id = os.getenv("CLIENT_ID")
    client_secret = os.getenv("CLIENT_SECRET")
    redirect_uri = os.getenv("STRAVA_REDIRECT_URI", "http://localhost")
    scope = os.getenv("STRAVA_SCOPE", "activity:read,activity:read_all")

    if not client_id or not client_secret:
        sys.exit("CLIENT_ID und CLIENT_SECRET in .env setzen.")

    q = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "force",
            "scope": scope,
        }
    )
    print("1. Im Browser öffnen und Zugriff erlauben:\n")
    print(f"{AUTH_URL}?{q}\n")
    print("2. Nach dem Redirect steht in der Adresszeile ?code=....")
    print("   Volle URL oder nur den code hier einfügen.\n")
    raw = input("URL oder code: ").strip()
    code = extract_code(raw)
    if not code:
        sys.exit("Kein code erkannt.")

    # Nur diese Felder — redirect_uri gehört nur zur Authorize-URL, nicht hierher.
    data = {
        "client_id": client_id,
        "client_secret": client_secret,
        "code": code,
        "grant_type": "authorization_code",
    }

    r = requests.post(TOKEN_URL, data=data, timeout=30)
    if r.status_code != 200:
        print(r.status_code, r.text)
        sys.exit(
            "Token-Tausch fehlgeschlagen. Häufig: code schon verbraucht oder abgelaufen (neu autorisieren), "
            "falsche CLIENT_ID/SECRET, oder redirect_uri in der Browser-URL weicht von STRAVA_REDIRECT_URI ab "
            "(muss in der Strava-App erlaubt sein, z. B. Domain localhost)."
        )

    body = r.json()
    refresh = body.get("refresh_token")
    access = body.get("access_token")
    if not refresh:
        sys.exit("Antwort ohne refresh_token — siehe JSON oben.")

    print("\nErfolg. Trage in .env ein (alten REFRESH_TOKEN ersetzen):\n")
    print(f"REFRESH_TOKEN={refresh}\n")
    if access:
        print(f"(access_token kurz zum Testen: {access[:20]}...)\n")


if __name__ == "__main__":
    main()
