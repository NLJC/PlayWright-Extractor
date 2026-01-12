import base64
import os
import queue
import re
import shutil
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import requests
from dotenv import load_dotenv

from helper_playwright import functions
from helper_playwright.auth_helper import get_token
from helper_playwright.paths import get_downloads_dir, get_email_attachment_dir
from playwright_scripts.run_playwright import PlaywrightRunner
from email_processing.attachment_utils import identify_file_type  # New import

load_dotenv()

SUBJECT_PATTERN = r"BANK RECON\s*[-–—]\s*(?P<account>[A-Za-z0-9]+)\s*[-–—]\s*(?P<date>\d{2}/\d{2}/\d{4})"
VALID_ATTACHMENT_NAMES = {
    "jompayreport.zip": "jompay",
    "merchantreport.zip": "merchant",
}


@dataclass
class ParsedAttachment:
    name: str
    path: Path
    category: str = "other"


@dataclass
class BankReconJob:
    message_id: str
    account: str
    recon_date: str
    amount: float
    sender: str
    subject: str
    attachments: List[ParsedAttachment]


def _graph_base(mailbox: Optional[str]) -> str:
    """Return the Microsoft Graph base path for the chosen mailbox."""
    if mailbox:
        return f"https://graph.microsoft.com/v1.0/users/{mailbox}"
    return "https://graph.microsoft.com/v1.0/me"


def _graph_headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def _clean_body(body_content: str) -> str:
    cleaned = re.sub(r"<[^>]+>", " ", body_content or "")
    cleaned = cleaned.replace("&nbsp;", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_amount(text: str) -> Optional[float]:
    match = re.search(r"([-+]?\d[\d,]*\.?\d*)", text.replace(" ", ""))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def _parse_subject(subject: str) -> Optional[dict]:
    match = re.search(SUBJECT_PATTERN, subject or "", flags=re.IGNORECASE)
    if not match:
        return None
    return {
        "account": match.group("account"),
        "date": match.group("date"),
    }


def _save_attachment(message_id: str, attachment: dict) -> ParsedAttachment:
    """Persist an attachment to the Downloads/email_attachments/{message_id} folder."""
    target_dir = get_email_attachment_dir(message_id)
    name = attachment.get("name", "attachment.bin")
    category = VALID_ATTACHMENT_NAMES.get(name.lower(), "other")

    data = attachment.get("contentBytes")
    if not data:
        return ParsedAttachment(name=name, path=target_dir / name, category=category)

    decoded = base64.b64decode(data)
    path = target_dir / name
    path.write_bytes(decoded)
    return ParsedAttachment(name=name, path=path, category=category)


def _write_trigger_marker(message_id: str) -> None:
    Path("trigger_email_id.txt").write_text(message_id, encoding="utf-8")


def _mark_as_read(token: str, mailbox: Optional[str], message_id: str) -> None:
    url = f"{_graph_base(mailbox)}/messages/{message_id}"
    requests.patch(url, headers=_graph_headers(token), json={"isRead": True}, timeout=15)


def _reply(token: str, mailbox: Optional[str], message_id: str, message: str) -> None:
    url = f"{_graph_base(mailbox)}/messages/{message_id}/reply"
    requests.post(url, headers=_graph_headers(token), json={"comment": message}, timeout=15)


def parse_bank_recon_message(message: dict) -> Tuple[Optional[BankReconJob], Optional[str]]:
    subject = message.get("subject", "")
    parsed_subject = _parse_subject(subject)
    if not parsed_subject:
        return None, "Subject does not match 'BANK RECON - <CASH ACCOUNT> - <DD/MM/YYYY>'."

    body = _clean_body(message.get("body", {}).get("content", ""))
    amount = _parse_amount(body)
    if amount is None:
        return None, "Unable to extract ending balance from the email body."

    attachments = message.get("attachments", []) or []
    parsed_attachments: List[ParsedAttachment] = []
    for att in attachments:
        parsed_attachments.append(_save_attachment(message["id"], att))

    sender = message.get("from", {}).get("emailAddress", {}).get("address", "")

    return (
        BankReconJob(
            message_id=message["id"],
            account=parsed_subject["account"],
            recon_date=parsed_subject["date"],
            amount=amount,
            sender=sender,
            subject=subject,
            attachments=parsed_attachments,
        ),
        None,
    )


class EmailTriggerQueue:
    """Simple email-driven queue that dispatches BANK RECON requests to Playwright."""

    def __init__(self, mailbox: Optional[str] = None):
        self.mailbox = mailbox or os.getenv("SUPPORT_MAILBOX") or os.getenv("USERNAME")
        self.queue: queue.Queue[BankReconJob] = queue.Queue()
        self.worker_thread: Optional[threading.Thread] = None
        self.logger = functions.setup_logger("EmailTriggerQueue", "email_trigger_queue.log")

    def poll_and_enqueue(self, max_results: int = 5) -> int:
        """Fetch unread emails and enqueue valid BANK RECON jobs."""
        token = get_token()
        headers = _graph_headers(token)
        url = f"{_graph_base(self.mailbox)}/messages?$top={max_results}&$filter=isRead eq false&$expand=attachments"
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()

        messages = response.json().get("value", [])
        added = 0
        for message in messages:
            job, error = parse_bank_recon_message(message)
            if not job:
                if error:
                    self.logger.warning(error)
                    _reply(token, self.mailbox, message["id"], f"[Error] {error}")
                    _mark_as_read(token, self.mailbox, message["id"])
                continue

            self.logger.info(
                "Queued BANK RECON email",
                extra={"subject": job.subject, "account": job.account, "date": job.recon_date},
            )
            self.queue.put(job)
            added += 1
            _reply(
                token,
                self.mailbox,
                job.message_id,
                f"[Queued] Job queued for {job.account} on {job.recon_date}",
            )
            _mark_as_read(token, self.mailbox, job.message_id)

        if added and (not self.worker_thread or not self.worker_thread.is_alive()):
            self.worker_thread = threading.Thread(target=self._worker, daemon=True)
            self.worker_thread.start()

        return added

    def _worker(self) -> None:
        """Worker loop that processes queued jobs sequentially."""
        # Store original SAVE_DIRECTORY to restore later
        original_save_dir = os.environ.get("SAVE_DIRECTORY")

        while not self.queue.empty():
            job: BankReconJob = self.queue.get()
            token = get_token()
            _write_trigger_marker(job.message_id)

            # --- PRE RECON STEP: Create Run Folder & Route Attachments ---
            try:
                # Create unique timestamped run folder
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                # Sanitize subject for folder name
                safe_subject = re.sub(r'[<>:"/\\|?*]', '_', job.subject).strip()
                run_folder_name = f"{timestamp}_{safe_subject}"
                
                # Use get_downloads_dir() base logic but manually constructed to avoid circular dependency loop if we altered it
                # Default is ProjectRoot/Downloads
                base_downloads = Path(__file__).resolve().parent.parent / "Downloads"
                # If SAVE_DIRECTORY was set globally, respect it as the root
                if original_save_dir:
                    base_downloads = Path(original_save_dir)
                
                # The specific run folder
                run_folder = base_downloads / "Runs" / run_folder_name
                
                # Subfolders
                attachments_dir = run_folder / "attachments"
                intermediates_dir = run_folder / "intermediates"
                outputs_dir = run_folder / "outputs"
                
                for d in [attachments_dir, intermediates_dir, outputs_dir]:
                    d.mkdir(parents=True, exist_ok=True)
                
                self.logger.info(f"Created Run Folder: {run_folder}")
                
                # Move/Copy attachments
                # Move/Copy attachments
                import zipfile # Ensure imported

                for att in job.attachments:
                    if att.path and att.path.exists():
                        # ZIP HANDLING
                        if att.path.suffix.lower() == ".zip":
                            try:
                                extract_root = att.path.parent / f"extracted_{att.path.stem}"
                                extract_root.mkdir(exist_ok=True)
                                with zipfile.ZipFile(att.path, "r") as zf:
                                    zf.extractall(extract_root)
                                
                                self.logger.info(f"Extracted zip {att.name} to {extract_root}")
                                
                                # Recursive scan
                                for f_path in extract_root.rglob("*"):
                                    if f_path.is_file() and not f_path.name.startswith(('.', '~')):
                                        file_type = identify_file_type(f_path)
                                        if file_type in ["DAILY_REPORT", "CREDIT_CARD"]:
                                            dest_path = attachments_dir / f_path.name
                                            shutil.copy2(f_path, dest_path)
                                            self.logger.info(f"Routed extracted file {f_path.name} -> {dest_path} (Type: {file_type})")
                            except Exception as zip_err:
                                self.logger.error(f"Failed to extract zip {att.name}: {zip_err}")
                            continue

                        # STANDARD FILE HANDLING
                        # Analyze content type using new utility
                        file_type = identify_file_type(att.path)
                        
                        dest_path = attachments_dir / att.path.name
                        shutil.copy2(att.path, dest_path)
                        self.logger.info(f"Copied attachment {att.name} to {dest_path} (Type: {file_type})")

                # SET ENVIRONMENT VARIABLE FOR THIS RUN
                # The PlaywrightRunner running in this process will pick this up
                # And downstream RaasPlus logic (via get_downloads_dir) will see this as the root
                os.environ["SAVE_DIRECTORY"] = str(run_folder)
                self.logger.info(f"Set SAVE_DIRECTORY env var to: {os.environ['SAVE_DIRECTORY']}")
                
            except Exception as e:
                self.logger.error(f"Failed to setup run folder: {e}")
                _reply(token, self.mailbox, job.message_id, f"[Error] Failed to setup run environment: {e}")
                self.queue.task_done()
                continue
            # -------------------------------------------------------------

            self.logger.info(f"Starting Playwright run for {job.account} on {job.recon_date}")
            _reply(
                token,
                self.mailbox,
                job.message_id,
                f"[Starting] BANK RECON for {job.account} ({job.recon_date}) - amount {job.amount}. Run ID: {run_folder_name}",
            )

            try:
                runner = PlaywrightRunner(
                    account_name=job.account,
                    date=job.recon_date,
                    amount=job.amount,
                )
                runner.run()
                _reply(
                    token,
                    self.mailbox,
                    job.message_id,
                    f"[Done] BANK RECON completed for {job.account} ({job.recon_date})",
                )
            except Exception as exc:
                self.logger.exception("BANK RECON job failed")
                _reply(
                    token,
                    self.mailbox,
                    job.message_id,
                    f"[Error] BANK RECON failed for {job.account} ({job.recon_date}): {exc}",
                )
            finally:
                # Cleanup: Restore environment variable
                if original_save_dir:
                    os.environ["SAVE_DIRECTORY"] = original_save_dir
                else:
                    os.environ.pop("SAVE_DIRECTORY", None)
                    
                _mark_as_read(token, self.mailbox, job.message_id)
                self.queue.task_done()

    def wait_for_completion(self) -> None:
        if self.worker_thread:
            self.worker_thread.join()
