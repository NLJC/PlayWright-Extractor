import json
import os

import msal
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("CLIENT_ID", "231e7253-117c-4ae1-ad1f-f93d82c6e36c")
RAW_CLIENT_SECRET = os.getenv("CLIENT_SECRET")
CLIENT_SECRET = (
    None
    if RAW_CLIENT_SECRET is None
    else (None if RAW_CLIENT_SECRET.strip().lower() in {"", "none", "null"} else RAW_CLIENT_SECRET.strip())
)
TENANT_ID = os.getenv("TENANT_ID", "eb83ccb1-6ce0-40b1-941c-c7b1e857a690")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = os.getenv("GRAPH_SCOPES", "Mail.ReadWrite Mail.Send").split()

TOKEN_CACHE_FILE = "token_cache.json"


def load_cache():
    """Loads the MSAL token cache from file if available."""
    cache = msal.SerializableTokenCache()
    if os.path.exists(TOKEN_CACHE_FILE):
        with open(TOKEN_CACHE_FILE, "r") as f:
            cache.deserialize(f.read())
    return cache


def save_cache(cache):
    """Saves the MSAL token cache to file."""
    if cache.has_state_changed:
        with open(TOKEN_CACHE_FILE, "w") as f:
            f.write(cache.serialize())


def _get_public_client_token():
    """Device flow (delegated) - no client secret required."""
    cache = load_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try cached token
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            save_cache(cache)
            return result["access_token"]

    # Device flow prompt
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception("Failed to create device flow")

    print("Please go to:", flow["verification_uri"])
    print("Enter this code:", flow["user_code"])
    print("Waiting for you to complete sign-in...")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        print("Authentication successful. Token cached for future use.")
        save_cache(cache)
        return result["access_token"]

    print("Authentication failed:")
    print(json.dumps(result, indent=2))
    raise SystemExit("Exiting... please try again.")


def _get_confidential_client_token():
    """Client credentials (application) - requires CLIENT_SECRET."""
    if not CLIENT_SECRET:
        raise ValueError("CLIENT_SECRET is required for client credentials flow.")

    app = msal.ConfidentialClientApplication(
        CLIENT_ID,
        client_credential=CLIENT_SECRET,
        authority=AUTHORITY,
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    if "access_token" in result:
        return result["access_token"]

    print("Authentication failed:")
    print(json.dumps(result, indent=2))
    raise SystemExit("Exiting... please check client credentials.")


def get_token():
    """
    Gets a valid access token.
    - If CLIENT_SECRET is provided, uses client credentials (application permissions).
    - Otherwise uses device code flow (delegated permissions).
    """
    if CLIENT_SECRET:
        return _get_confidential_client_token()
    return _get_public_client_token()
