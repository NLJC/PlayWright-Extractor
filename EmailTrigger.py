import re
import msal
import requests
from playwright.sync_api import sync_playwright
import os
from CAMatchExtract import CAMatchExtract  # 👈 import your function

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
        print("❌ Authentication failed:", result.get("error_description"))
        raise SystemExit("Exiting... please try again.")

def get_latest_email(token):
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "https://graph.microsoft.com/v1.0/me/messages?$top=1"
    response = requests.get(endpoint, headers=headers)

    if response.status_code != 200:
        print("❌ Error fetching email:", response.text)
        return None

    msg = response.json().get("value", [])[0]
    subject = msg["subject"]
    sender = msg["from"]["emailAddress"]["address"]
    message_id = msg["id"]
    body_content = msg.get("body", {}).get("content", "")
    body_text = re.sub("<[^<]+?>", "", body_content).strip()

    print(f"\n📧 Received: {subject}")
    print(f"From: {sender}")
    print(f"Body: {body_text}\n")

    # --- 💾 Save trigger email ID for the reply system ---
    with open("trigger_email_id.txt", "w") as f:
        f.write(message_id)
    print(f"📝 Saved trigger email ID: {message_id}")

    return subject, body_text, message_id

def parse_bank_recon_email(subject, body):
    match = re.match(r"BANK RECON\s*-\s*([A-Za-z0-9]+)\s*-\s*(\d{2}/\d{2}/\d{4})", subject)
    if not match:
        return None

    account = match.group(1)
    date = match.group(2)

    try:
        amount = float(body.strip().replace(",", ""))
    except ValueError:
        print("⚠️ Invalid amount in email body.")
        return None

    return {"account": account, "date": date, "amount": amount}

def run_program(account, date, amount):
    """Runs your CAMatchExtract function correctly using Playwright."""
    print(f"🚀 Starting CAMatchExtract for {account} ({date}), amount {amount}")

    with sync_playwright() as playwright:
        CAMatchExtract(
            playwright=playwright,
            accountName=account,
            date=date,
            amount=amount,
            website_url=os.getenv("WEBSITE_URL"),
            username=os.getenv("WEBSITE_USERNAME"),
            password=os.getenv("PASSWORD"),
            pingback_url=None,
            payload=None,
            webhook_url=None,
        )

    print("✅ CAMatchExtract finished successfully!")

if __name__ == "__main__":
    token = get_access_token()
    subject, body, message_id = get_latest_email(token)

    if "BANK RECON" in subject.upper():
        info = parse_bank_recon_email(subject, body)
        if info:
            run_program(info["account"], info["date"], info["amount"])
        else:
            print("⚠️ Could not parse BANK RECON email format.")
    else:
        print("📭 No BANK RECON command detected in latest email.")
