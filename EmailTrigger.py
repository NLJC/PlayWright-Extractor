import msal
import requests

CLIENT_ID = "231e7253-117c-4ae1-ad1f-f93d82c6e36c"
TENANT_ID = "eb83ccb1-6ce0-40b1-941c-c7b1e857a690"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Mail.Read"]

def get_access_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception("Failed to create device flow")

    print("Please go to:", flow["verification_uri"])
    print("And enter this code:", flow["user_code"])
    print("Waiting for you to complete sign-in...")

    result = app.acquire_token_by_device_flow(flow)  # Blocks until done or times out

    # Handle errors gracefully
    if "access_token" in result:
        print("✅ Authentication successful!")
        return result["access_token"]
    else:
        print("❌ Authentication failed:")
        print(result.get("error"))
        print(result.get("error_description"))
        print(result.get("correlation_id"))  # Useful for debugging with Microsoft support
        raise SystemExit("Exiting... please try again.")

def read_emails(token):
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "https://graph.microsoft.com/v1.0/me/messages?$top=5"
    response = requests.get(endpoint, headers=headers)
    if response.status_code == 200:
        for msg in response.json().get("value", []):
            print(f"📧 {msg['subject']} from {msg['from']['emailAddress']['address']}")
    else:
        print("❌ Error:", response.text)

if __name__ == "__main__":
    token = get_access_token()
    read_emails(token)
