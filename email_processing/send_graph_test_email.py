import base64
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import requests
from dotenv import load_dotenv, dotenv_values

# Ensure project root is on path when running as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from helper_playwright.auth_helper import get_token, CLIENT_SECRET

load_dotenv(override=True)


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def build_message(recipient: str, sender: str, attachments: Optional[List[Dict]] = None) -> dict:
    """
    Compose a recon-trigger email that Playwright will detect.
    Subject format: BANK RECON - <ACCOUNT> - <DD/MM/YYYY>
    Body: single-line amount value.
    """
    # Allow overriding via env; fall back to accountName or default CIM02
    account = (
        os.getenv("RECON_ACCOUNT")
        or os.getenv("accountName")
        or os.getenv("ACCOUNT_NAME")
        or "CIM02"
    )
    # Allow passing explicit date; default to today in DD/MM/YYYY
    recon_date = os.getenv("RECON_DATE") or datetime.utcnow().strftime("%d/%m/%Y")
    amount = os.getenv("RECON_AMOUNT") or "263737.84"

    subject = f"BANK RECON - {account} - {recon_date}"
    body = f"{amount}"
    return {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": recipient}}],
            "from": {"emailAddress": {"address": sender}},
            "attachments": attachments or [],
        },
        "saveToSentItems": "true",
    }


def main():
    env_file = dotenv_values()
    recipient = (
        env_file.get("SUPPORT_MAILBOX")
        or os.getenv("SUPPORT_MAILBOX")
        or env_file.get("USERNAME")
        or os.getenv("USERNAME")
    )
    if not recipient:
        print("SUPPORT_MAILBOX or USERNAME (email) is not set in .env; cannot send test email.")
        sys.exit(1)

    sender = (
        env_file.get("USERNAME")
        or os.getenv("USERNAME")
        or recipient
    )
    token = get_token()

    # Delegated tokens should use /me/sendMail; app tokens can target any mailbox
    if CLIENT_SECRET:
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    else:
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    attachments: List[Dict] = []
    if env_bool("SEND_ZIP_ATTACHMENT", default=True):
        zip_path = ROOT_DIR / "daily_report_folder" / "extrafiles.zip"
        if zip_path.exists():
            content_bytes = base64.b64encode(zip_path.read_bytes()).decode("ascii")
            attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": zip_path.name,
                    "contentType": "application/zip",
                    "contentBytes": content_bytes,
                }
            )
            print(f"Attaching {zip_path} ({len(content_bytes)} base64 chars).")
        else:
            print(f"Attachment enabled but file not found: {zip_path}. Continuing without attachment.")

    payload = build_message(recipient, sender, attachments=attachments)
    resp = requests.post(url, headers=headers, json=payload, timeout=15)

    if resp.status_code in (200, 202):
        print(f"OK. Test mail queued to {recipient}")
        sys.exit(0)
    else:
        print(f"Failed to send test mail: {resp.status_code}")
        print(resp.text)
        sys.exit(1)


if __name__ == "__main__":
    main()
