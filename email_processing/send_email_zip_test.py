import base64
import os
import sys
import zipfile
import shutil
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

def build_message(recipient: str, sender: str, attachments: Optional[List[Dict]] = None) -> dict:
    account = "CIMB" # Force MBB02 for testing credit card logic
    recon_date = datetime.utcnow().strftime("%d/%m/%Y")
    amount = "0.00"    # Arbitrary amount to distinguish run

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

    if CLIENT_SECRET:
        url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    else:
        url = "https://graph.microsoft.com/v1.0/me/sendMail"
        
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    attachments: List[Dict] = []
    
    # 1. Prepare Zip
    temp_zip_dir = ROOT_DIR / "temp_zip_test"
    temp_zip_dir.mkdir(exist_ok=True)
    zip_path = temp_zip_dir / "test_bundle.zip"
    
    jompay_path = ROOT_DIR / "daily_report_folder" / "daily_transaction_report.xlsx"
    cc_path = ROOT_DIR / "test_dataset" / "dbkkdemodataset" / "027007700511_T41_20251111.csv"
    
    print(f"Creating zip at {zip_path}...")
    with zipfile.ZipFile(zip_path, "w") as zf:
        if jompay_path.exists():
            zf.write(jompay_path, arcname="folder/daily_transaction_report.xlsx") # Add folder nesting
        if cc_path.exists():
            zf.write(cc_path, arcname="027007700511_T41_20251111.csv")
            
    # 2. Attach Zip
    if zip_path.exists():
        content_bytes = base64.b64encode(zip_path.read_bytes()).decode("ascii")
        attachments.append(
            {
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": "test_bundle.zip",
                "contentType": "application/zip",
                "contentBytes": content_bytes,
            }
        )
        print(f"Added attachment: {zip_path.name}")
    else:
        print(f"WARNING: Zip file creation failed.")
        sys.exit(1)

    payload = build_message(recipient, sender, attachments=attachments)
    
    print(f"Sending email to {recipient}...")
    resp = requests.post(url, headers=headers, json=payload, timeout=20)

    if resp.status_code in (200, 202):
        print(f"OK. Test mail queued with ZIP attachment.")
    else:
        print(f"Failed to send test mail: {resp.status_code}")
        print(resp.text)
        sys.exit(1)
        
    # Cleanup
    shutil.rmtree(temp_zip_dir)

if __name__ == "__main__":
    main()
