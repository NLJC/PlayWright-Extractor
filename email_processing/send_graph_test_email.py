import os
import sys
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv, dotenv_values

# Ensure project root is on path when running as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from helper_playwright.auth_helper import get_token, CLIENT_SECRET

load_dotenv(override=True)


def build_message(recipient: str, sender: str) -> dict:
    timestamp = datetime.utcnow().isoformat()
    subject = f"Graph SMTP test {timestamp}"
    body = (
        "This is a Graph sendMail test to confirm the current token works.\n"
        f"Sender: {sender}\n"
        f"Recipient: {recipient}\n"
        f"Timestamp (UTC): {timestamp}\n"
    )
    return {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
            "from": {"emailAddress": {"address": sender}},
        },
        "saveToSentItems": "true",
    }


def main():
    env_file = dotenv_values()
    recipient = (
        env_file.get("SUPPORT_MAILBOX")
        or env_file.get("USERNAME")
        or os.getenv("SUPPORT_MAILBOX")
        or os.getenv("USERNAME")
    )
    if not recipient:
        print("SUPPORT_MAILBOX or USERNAME (email) is not set in .env; cannot send test email.")
        sys.exit(1)

    sender = recipient
    token = get_token()

    # Delegated tokens should use /me/sendMail; app tokens can target any mailbox
    if CLIENT_SECRET:
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    else:
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
    headers = {
        "client_id": os.getenv("CLIENT_ID"),
        "client_secret ": os.getenv("CLIENT_SECRET"),
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    payload = build_message(recipient, sender)
    resp = requests.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code in (200, 202):
        print(f"✅ Test mail queued to {recipient}")
        sys.exit(0)
    else:
        print(f"❌ Failed to send test mail: {resp.status_code}")
        print(resp.text)
        sys.exit(1)


if __name__ == "__main__":
    main()
