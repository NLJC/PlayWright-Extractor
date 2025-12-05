Email-triggered Playwright flow (24/7)
======================================

This listener watches the mailbox for unread recon emails, queues them, extracts details, downloads attachments, and sends them one-by-one into the Playwright recon flow.

Prerequisites
-------------
- `.env` set with Graph creds and mailbox:
  - `CLIENT_ID`, `TENANT_ID`, `CLIENT_SECRET`
  - `SUPPORT_MAILBOX` (or `USERNAME`) = mailbox to watch/send
  - `GRAPH_SCOPES` should include `Mail.ReadWrite Mail.Send`
- App has `Mail.Read` (and `Mail.Send` if you send test mail) with admin consent for the target mailbox.

Key scripts
-----------
- `email_processing/inbox_listener.py` - 24/7 listener for unread emails; matches subject, downloads/extracts attachments, parses recon fields, and calls Playwright sequentially.
- `email_processing/send_graph_test_email.py` - sends a recon-style email (optional test trigger).
- `run_playwright.py` - runs the Playwright workflow.

Listener env toggles
--------------------
- `LISTENER_SUBJECT_PATTERN` (default `BANK RECON -`)
- `LISTENER_POLL_SECONDS` (default `20`)
- `LISTENER_ATTACHMENT_DIR` (default `<repo>/Downloads/inbox`)
- `LISTENER_BATCH_SIZE` (default `20`) how many unread messages to pull per poll
- `RUN_PLAYWRIGHT_ENABLED` (default `true`) toggle to launch Playwright per matched email

Send-mail overrides (optional test)
-----------------------------------
- `RECON_ACCOUNT`, `RECON_DATE` (DD/MM/YYYY), `RECON_AMOUNT`
- `SEND_ZIP_ATTACHMENT` (default `true`), expects `daily_report_folder/extrafiles.zip`

How to run (24/7 queue processor)
---------------------------------
PowerShell:
```
python email_processing/inbox_listener.py
```
With custom pattern/locations:
```
LISTENER_SUBJECT_PATTERN="BANK RECON -" `
LISTENER_ATTACHMENT_DIR="C:\Temp\email_downloads" `
LISTENER_POLL_SECONDS=15 `
python email_processing/inbox_listener.py
```
The listener never exits; stop with Ctrl+C. It processes unread messages newest-first each poll, one at a time.

Optional: send a trigger email from this machine
-----------------------------------------------
```
python email_processing/send_graph_test_email.py
```
Or with overrides:
```
RECON_ACCOUNT=CIM02 RECON_DATE=31/07/2025 RECON_AMOUNT=263737.84 SEND_ZIP_ATTACHMENT=true `
python email_processing/send_graph_test_email.py
```

What happens
------------
- Listener polls for unread Inbox messages; filters by subject containing `LISTENER_SUBJECT_PATTERN`.
- For each match (in order), it downloads attachments to `LISTENER_ATTACHMENT_DIR/<messageId>` and auto-extracts any `.zip`.
- It parses account/date/amount from subject/body and calls `run_playwright.py` with `--account/--date/--amount` sequentially.
- On success, the message is marked as read to avoid reprocessing; seen IDs are tracked in-memory during the session. Stop/start will skip already-read mail by design.
