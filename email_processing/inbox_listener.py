import base64
import os
import re
import subprocess
import sys
import time
import zipfile
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


def message_base_url(user: str) -> str:
    if CLIENT_SECRET:
        return f"https://graph.microsoft.com/v1.0/users/{user}"
    return "https://graph.microsoft.com/v1.0/me"


def fetch_unread_messages(user: str, top: int = 20) -> List[Dict]:
    """Fetch unread messages ordered by receivedDateTime desc."""
    url = f"{message_base_url(user)}/mailFolders/Inbox/messages"
    params = {
        "$top": top,
        "$select": "id,subject,from,receivedDateTime,isRead",
        "$filter": "isRead eq false",
        "$orderby": "receivedDateTime desc",
    }
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise SystemExit(f"Failed to fetch unread messages ({resp.status_code}): {resp.text}")
    return resp.json().get("value", [])


def mark_as_read(user: str, message_id: str):
    url = f"{message_base_url(user)}/messages/{message_id}"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    resp = requests.patch(url, headers=headers, json={"isRead": True}, timeout=15)
    if resp.status_code not in (200, 202):
        print(f"Warning: failed to mark message {message_id} as read ({resp.status_code}) {resp.text}")


def fetch_message_detail(user: str, message_id: str) -> Dict:
    url = f"{message_base_url(user)}/messages/{message_id}"
    params = {"$select": "id,subject,body,bodyPreview,receivedDateTime,from"}
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, params=params, timeout=15)
    if resp.status_code != 200:
        raise SystemExit(f"Failed to fetch message detail ({resp.status_code}): {resp.text}")
    return resp.json()


def html_to_text(html: str) -> str:
    # Minimal HTML stripper; avoids extra dependency
    return re.sub(r"<[^>]+>", " ", html or "")


def parse_recon_payload(subject: str, body_text: str) -> Dict[str, Optional[str]]:
    account = None
    recon_date = None
    parts = [p.strip() for p in subject.split("-")]
    if len(parts) >= 3:
        account = parts[1] or None
        recon_date = parts[2] or None

    amount = None
    # Find first decimal number, allow commas
    match = re.search(r"([0-9][0-9,]*\.[0-9]{2})", body_text)
    if match:
        amount = match.group(1).replace(",", "")

    return {
        "subject": subject,
        "account": account,
        "date": recon_date,
        "amount": amount,
    }


def download_attachments(user: str, message_id: str, dest_dir: Path, extract_zip: bool = True) -> List[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"{message_base_url(user)}/messages/{message_id}/attachments"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    resp = requests.get(url, headers=headers, timeout=20)
    if resp.status_code != 200:
        raise SystemExit(f"Failed to fetch attachments ({resp.status_code}): {resp.text}")

    saved: List[Path] = []
    for att in resp.json().get("value", []):
        if att.get("@odata.type") != "#microsoft.graph.fileAttachment":
            continue
        name = att.get("name") or "attachment.bin"
        content_b64 = att.get("contentBytes")
        if not content_b64:
            continue
        data = base64.b64decode(content_b64)
        target = dest_dir / name
        target.write_bytes(data)
        saved.append(target)

        if extract_zip and target.suffix.lower() == ".zip":
            extract_dir = target.with_suffix("")
            extract_dir.mkdir(exist_ok=True)
            try:
                with zipfile.ZipFile(target, "r") as zf:
                    zf.extractall(extract_dir)
                print(f"Extracted {target.name} to {extract_dir}")
            except Exception as exc:
                print(f"Warning: failed to extract {target}: {exc}")
    return saved


def send_failure_email(user: str, to_addr: str, subject_hint: str, error_text: str):
    """Notify sender about failure."""
    if not to_addr:
        return

    url = f"{message_base_url(user)}/sendMail"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    subject = f"RPA Process Failed - {subject_hint or 'BANK RECON'}"
    body = (
        "Hello,\n\n"
        "The RPA bank reconciliation process could not be completed after multiple attempts.\n"
        f"Error: {error_text}\n\n"
        "Please contact CC support at support@cognitive.com.my.\n\n"
        "Thank you."
    )
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_addr}}],
        },
        "saveToSentItems": "true",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=15)
        if resp.status_code not in (200, 202):
            print(f"Warning: failed to send failure email to {to_addr} ({resp.status_code}) {resp.text}")
    except Exception as exc:
        print(f"Warning: exception sending failure email: {exc}")


def latest_matching_result() -> Optional[Path]:
    out_dir = ROOT_DIR / "matching_results"
    if not out_dir.exists():
        return None
    candidates = sorted(out_dir.glob("MATCHLIST_*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def send_success_email(user: str, to_addr: str, account: str, recon_date: str, amount: str):
    """Notify sender about success and attach latest matching result."""
    if not to_addr:
        return

    url = f"{message_base_url(user)}/sendMail"
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }
    subject = f"RPA Reconciliation Completed - {account or 'Account'} - {recon_date or 'Date'}"
    body = (
        "Hello,\n\n"
        "Your bank reconciliation RPA process has completed successfully.\n"
        f"Account: {account or 'N/A'}\n"
        f"Date: {recon_date or 'N/A'}\n"
        f"Amount: {amount or 'N/A'}\n\n"
        "The latest matching results are attached if available.\n\n"
        "Thank you."
    )

    attachments = []
    result_path = latest_matching_result()
    if result_path and result_path.exists():
        try:
            content_b64 = base64.b64encode(result_path.read_bytes()).decode("ascii")
            attachments.append(
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": result_path.name,
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "contentBytes": content_b64,
                }
            )
        except Exception as exc:
            print(f"Warning: failed to attach {result_path}: {exc}")

    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "Text", "content": body},
            "toRecipients": [{"emailAddress": {"address": to_addr}}],
            "attachments": attachments,
        },
        "saveToSentItems": "true",
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code not in (200, 202):
            print(f"Warning: failed to send success email to {to_addr} ({resp.status_code}) {resp.text}")
    except Exception as exc:
        print(f"Warning: exception sending success email: {exc}")


def run_playwright_job(account: Optional[str], recon_date: Optional[str], amount: Optional[str]):
    cmd = [sys.executable, str(ROOT_DIR / "run_playwright.py")]
    if account:
        cmd.extend(["--account", account])
    if recon_date:
        cmd.extend(["--date", recon_date])
    if amount:
        try:
            float(amount)
            cmd.extend(["--amount", amount])
        except ValueError:
            print(f"Warning: amount '{amount}' not numeric; skipping amount param.")

    print(f"Starting Playwright: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=ROOT_DIR)
    if result.returncode != 0:
        print(f"Playwright run failed with code {result.returncode}")
    else:
        print("Playwright run completed.")
    return result.returncode


def process_message(user: str, msg: Dict, subject_match: str, attachment_root: Path) -> bool:
    subject = msg.get("subject", "")
    msg_id = msg.get("id")
    if not msg_id or subject_match.lower() not in subject.lower():
        return False
    sender_addr = (
        msg.get("from", {})
        .get("emailAddress", {})
        .get("address", "")
    ).lower()

    # Skip our own notification emails to avoid loops; mark them read.
    if "rpa process failed" in subject.lower() or "rpa reconciliation completed" in subject.lower():
        print(f"Skipping notification email {msg_id} (subject: {subject})")
        mark_as_read(user, msg_id)
        return False
    if sender_addr and sender_addr == str(user).lower():
        print(f"Skipping self-sent email {msg_id} from {sender_addr}")
        mark_as_read(user, msg_id)
        return False

    print(f"Processing message {msg_id}: {subject}")
    detail = fetch_message_detail(user, msg_id)
    body_content = detail.get("body", {}).get("content", "") or detail.get("bodyPreview", "")
    body_type = detail.get("body", {}).get("contentType", "text").lower()
    if "html" in body_type:
        body_text = html_to_text(body_content)
    else:
        body_text = body_content or ""

    parsed = parse_recon_payload(subject, body_text)
    msg_dir = attachment_root / msg_id
    attachments = download_attachments(user, msg_id, msg_dir, extract_zip=True)
    parsed["attachments"] = [str(p) for p in attachments]
    parsed["message_id"] = msg_id
    sender_addr = (
        detail.get("from", {})
        .get("emailAddress", {})
        .get("address")
    )

    print(f"Parsed payload: account={parsed.get('account')}, date={parsed.get('date')}, amount={parsed.get('amount')}")

    run_playwright = env_bool("RUN_PLAYWRIGHT_ENABLED", True)
    max_retries = int(os.getenv("RUN_PLAYWRIGHT_MAX_RETRIES", "3"))
    last_error = None
    success = False
    if run_playwright:
        for attempt in range(1, max_retries + 1):
            rc = run_playwright_job(parsed.get("account"), parsed.get("date"), parsed.get("amount"))
            if rc == 0:
                success = True
                break
            last_error = f"Exit code {rc}"
            print(f"Attempt {attempt}/{max_retries} failed ({last_error}); retrying...")
        if not success:
            send_failure_email(user, sender_addr, subject, last_error or "Unknown error")
            print("Max retries reached; notified sender.")
    else:
        print("RUN_PLAYWRIGHT_ENABLED=false; skipping Playwright run.")

    mark_as_read(user, msg_id)
    if success:
        send_success_email(
            user=user,
            to_addr=sender_addr,
            account=parsed.get("account"),
            recon_date=parsed.get("date"),
            amount=parsed.get("amount"),
        )
    return success


def main():
    env_file = dotenv_values()
    user = (
        env_file.get("SUPPORT_MAILBOX")
        or env_file.get("USERNAME")
        or os.getenv("SUPPORT_MAILBOX")
        or os.getenv("USERNAME")
    )
    if not user:
        print("SUPPORT_MAILBOX or USERNAME (email) is not set in .env; cannot listen to inbox.")
        sys.exit(1)

    subject_match = os.getenv("LISTENER_SUBJECT_PATTERN", "BANK RECON -")
    poll_seconds = int(os.getenv("LISTENER_POLL_SECONDS", "20"))
    attachment_root = Path(os.getenv("LISTENER_ATTACHMENT_DIR", str(ROOT_DIR / "Downloads/inbox"))).expanduser()
    max_batch = int(os.getenv("LISTENER_BATCH_SIZE", "20"))

    print(f"24/7 listener started for {user}; subject contains '{subject_match}'; poll {poll_seconds}s.")
    seen_ids: set = set()
    while True:
        try:
            messages = fetch_unread_messages(user, top=max_batch)
            # Process newest first; already ordered desc
            for msg in messages:
                msg_id = msg.get("id")
                if not msg_id or msg_id in seen_ids:
                    continue
                handled = process_message(user, msg, subject_match, attachment_root)
                seen_ids.add(msg_id)
                # Sequential; continue to next after Playwright returns
        except KeyboardInterrupt:
            print("Listener stopped by user.")
            break
        except Exception as exc:
            print(f"Listener error: {exc}")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
