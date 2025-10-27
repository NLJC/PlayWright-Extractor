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

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        print("✅ Authentication successful!")
        return result["access_token"]
    else:
        print("❌ Authentication failed:")
        print(result.get("error_description"))
        raise SystemExit("Exiting... please try again.")

def get_latest_email(token):
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "https://graph.microsoft.com/v1.0/me/messages?$top=1"
    response = requests.get(endpoint, headers=headers)

    if response.status_code == 200:
        msg = response.json().get("value", [])[0]
        subject = msg["subject"]
        sender = msg["from"]["emailAddress"]["address"]
        message_id = msg["id"]

        print(f"📧 {subject} from {sender}")
        print(f"   ID: {message_id}")

        # Save message ID for later use
        with open("trigger_email_id.txt", "w") as f:
            f.write(message_id)

        return message_id
    else:
        print("❌ Error:", response.text)
        return None

if __name__ == "__main__":
    token = get_access_token()
    get_latest_email(token)
