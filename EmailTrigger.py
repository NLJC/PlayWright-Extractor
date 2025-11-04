import re
import msal
import requests
import subprocess
import threading
import queue
import os
import base64
from playwright.sync_api import sync_playwright

# ============================================================
# ✅ EMAIL AUTH
# ============================================================

CLIENT_ID = "231e7253-117c-4ae1-ad1f-f93d82c6e36c"
TENANT_ID = "eb83ccb1-6ce0-40b1-941c-c7b1e857a690"
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
SCOPES = ["Mail.ReadWrite", "Mail.Send"]

def get_access_token():
    app = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        raise Exception("Failed to create device flow")

    print("🔐 Go to:", flow["verification_uri"])
    print("🪪 Enter code:", flow["user_code"])
    print("Waiting for login...")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" in result:
        return result["access_token"]
    else:
        raise Exception("Authentication failed.")

# ============================================================
# ✅ STATUS EMAILS (Reply to same thread)
# ============================================================

def send_email_reply(token, message, attachment=None):
    try:
        with open("trigger_email_id.txt", "r") as f:
            message_id = f.read().strip()
    except:
        print("⚠️ No trigger_email_id.txt")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    # --------------------------------------------------------
    # If no attachment → simple reply
    # --------------------------------------------------------
    if not attachment:
        url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/reply"
        body = { "comment": message }
        requests.post(url, headers=headers, json=body)
        return

    # --------------------------------------------------------
    # With attachment → create draft
    # --------------------------------------------------------
    url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/createReply"
    draft = requests.post(url, headers=headers, json={"comment": message}).json()
    draft_id = draft["id"]

    # attach file
    filename = os.path.basename(attachment)
    with open(attachment, "rb") as f:
        file_b64 = base64.b64encode(f.read()).decode("utf-8")

    attach_data = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": filename,
        "contentBytes": file_b64,
    }

    attach_url = f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/attachments"
    requests.post(attach_url, headers=headers, json=attach_data)

    # send it
    send_url = f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/send"
    requests.post(send_url, headers=headers)

# ============================================================
# ✅ QUEUE + WORKER
# ============================================================

task_queue = queue.Queue()
is_running = False

def worker():
    global is_running
    is_running = True

    while not task_queue.empty():
        task = task_queue.get()
        params = task["params"]

        token = get_access_token()

        # status: started
        send_email_reply(token, f"🚀 Job started for {params['account']} on {params['date']}")

        try:
            subprocess.run(
                [
                    "python", "CAMatchExtract.py",
                    params["account"], params["date"], str(params["amount"])
                ],
                check=True
            )
            # status: finished
            send_email_reply(token, f"✅ Job finished successfully for {params['account']}")

            # If CAMatchExtract outputs a file, attach it here:
            # send_email_reply(token, "✅ Here is your reconciliation file", attachment="path")

        except Exception as e:
            send_email_reply(token, f"❌ Job FAILED\n{str(e)}")

        task_queue.task_done()

    is_running = False

def add_task(params):
    task_queue.put({"params": params})

    token = get_access_token()
    send_email_reply(token, f"📥 Job queued for {params['account']} ({params['date']})")

    global is_running
    if not is_running:
        threading.Thread(target=worker, daemon=True).start()

# ============================================================
# ✅ EMAIL TRIGGER
# ============================================================

def get_latest_email(token):
    headers = {"Authorization": f"Bearer {token}"}
    endpoint = "https://graph.microsoft.com/v1.0/me/messages?$top=1"
    response = requests.get(endpoint, headers=headers)

    msg = response.json()["value"][0]
    subject = msg["subject"]
    message_id = msg["id"]
    body_content = msg["body"]["content"]
    body_text = re.sub("<[^<]+?>","", body_content).strip()

    # save email ID
    with open("trigger_email_id.txt", "w") as f:
        f.write(message_id)

    return subject, body_text

def parse_bank_recon_email(subject, body):
    match = re.match(r"BANK RECON\s*-\s*([A-Za-z0-9]+)\s*-\s*(\d{2}/\d{2}/\d{4})", subject)
    if not match:
        return None

    account = match.group(1)
    date = match.group(2)
    amount = float(body.replace(",", "").strip())

    return {"account": account, "date": date, "amount": amount}

# ============================================================
# ✅ ENTRY POINT
# ============================================================

if __name__ == "__main__":
    token = get_access_token()
    subject, body = get_latest_email(token)

    if "BANK RECON" in subject.upper():
        info = parse_bank_recon_email(subject, body)

        if info:
            add_task(info)
        else:
            send_email_reply(token, "⚠️ Invalid BANK RECON format.")

    else:
        print("📭 No BANK RECON command")
