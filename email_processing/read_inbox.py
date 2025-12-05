import os
import sys
from pathlib import Path
from typing import List, Dict

import requests
from dotenv import load_dotenv, dotenv_values

# Ensure project root is on path when running as a script
ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from helper_playwright.auth_helper import get_token, CLIENT_SECRET

load_dotenv(override=True)


def fetch_inbox_messages(user: str, top: int = 10) -> List[Dict]:
    """
    Fetch the latest messages from the specified user's Inbox.
    Uses application permissions when CLIENT_SECRET is set; otherwise delegated.
    """
    if CLIENT_SECRET:
        url = f"https://graph.microsoft.com/v1.0/users/{user}/mailFolders/Inbox/messages"
    else:
        url = "https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages"

    params = {
        "$top": top,
        "$select": "id,subject,from,receivedDateTime,bodyPreview",
        "$orderby": "receivedDateTime desc",
    }
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }

    resp = requests.get(url, headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise SystemExit(f"Failed to read inbox ({resp.status_code}): {resp.text}")

    data = resp.json()
    return data.get("value", [])


def main():
    env_file = dotenv_values()
    user = (
        env_file.get("SUPPORT_MAILBOX")
        or env_file.get("USERNAME")
        or os.getenv("SUPPORT_MAILBOX")
        or os.getenv("USERNAME")
    )
    if not user:
        print("SUPPORT_MAILBOX or USERNAME (email) is not set in .env; cannot read inbox.")
        sys.exit(1)

    top = int(os.getenv("INBOX_TOP", "10"))
    messages = fetch_inbox_messages(user, top=top)

    print(f"Inbox for {user} (top {top}):")
    if not messages:
        print("No messages returned.")
        return

    for idx, msg in enumerate(messages, start=1):
        from_addr = (
            msg.get("from", {})
            .get("emailAddress", {})
            .get("address", "unknown")
        )
        subject = msg.get("subject", "(no subject)")
        received = msg.get("receivedDateTime", "")
        print(f"{idx:02d}. {received} | {from_addr} | {subject}")


if __name__ == "__main__":
    main()
