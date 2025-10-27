import msal
import os
import json

CLIENT_ID = "231e7253-117c-4ae1-ad1f-f93d82c6e36c"
TENANT_ID = "eb83ccb1-6ce0-40b1-941c-c7b1e857a690"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Mail.ReadWrite", "Mail.Send"]

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

def get_token():
    """Gets a valid access token, refreshing it automatically if needed."""
    cache = load_cache()
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)

    # Try to get a cached token
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            save_cache(cache)
            return result["access_token"]

    # If no cached token, start device flow
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception("Failed to create device flow")

    print("🔐 Please go to:", flow["verification_uri"])
    print("🪪 Enter this code:", flow["user_code"])
    print("Waiting for you to complete sign-in...")

    result = app.acquire_token_by_device_flow(flow)

    if "access_token" in result:
        print("✅ Authentication successful! Token cached for future use.")
        save_cache(cache)
        return result["access_token"]
    else:
        print("❌ Authentication failed:")
        print(json.dumps(result, indent=2))
        raise SystemExit("Exiting... please try again.")
