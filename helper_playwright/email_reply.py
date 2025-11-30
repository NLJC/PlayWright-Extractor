import base64
import os

import requests

from helper_playwright.auth_helper import get_token

def reply_to_trigger_email(reply_text):
    """Replies to the original trigger email stored in trigger_email_id.txt"""
    try:
        with open("trigger_email_id.txt", "r") as f:
            message_id = f.read().strip()
    except FileNotFoundError:
        print("⚠️ No trigger_email_id.txt found — can't reply.")
        return

    token = get_token()
    endpoint = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/reply"

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    body = {"comment": reply_text}
    response = requests.post(endpoint, headers=headers, json=body)

    if response.status_code == 202:
        print(f"✅ Replied successfully to the trigger email ({message_id})")
    else:
        print(f"❌ Failed to reply: {response.status_code}")
        print(response.text)

def reply_with_attachment(reply_text, attachment_path):
    """Replies to the trigger email (from trigger_email_id.txt) with an attachment."""
    try:
        with open("trigger_email_id.txt", "r") as f:
            message_id = f.read().strip()
    except FileNotFoundError:
        print("⚠️ No trigger_email_id.txt found — can't reply.")
        return

    token = get_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    # --- Step 1: Create a draft reply ---
    create_draft_url = f"https://graph.microsoft.com/v1.0/me/messages/{message_id}/createReply"
    create_draft_body = {"comment": reply_text}
    create_draft_response = requests.post(create_draft_url, headers=headers, json=create_draft_body)

    if create_draft_response.status_code != 201:
        print(f"❌ Failed to create draft reply: {create_draft_response.status_code}")
        print(create_draft_response.text)
        return

    draft_id = create_draft_response.json()["id"]
    print(f"📝 Draft reply created (ID: {draft_id})")

    # --- Step 2: Attach file to draft ---
    filename = os.path.basename(attachment_path)
    with open(attachment_path, "rb") as f:
        file_content = f.read()
    file_base64 = base64.b64encode(file_content).decode("utf-8")

    attachment_data = {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": filename,
        "contentBytes": file_base64,
    }

    attach_url = f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/attachments"
    attach_response = requests.post(attach_url, headers=headers, json=attachment_data)

    if attach_response.status_code != 201:
        print(f"❌ Failed to attach file: {attach_response.status_code}")
        print(attach_response.text)
        return

    print(f"📎 Attached file: {filename}")

    # --- Step 3: Send the draft reply ---
    send_url = f"https://graph.microsoft.com/v1.0/me/messages/{draft_id}/send"
    send_response = requests.post(send_url, headers=headers)

    if send_response.status_code == 202:
        print("✅ Reply with attachment sent successfully!")
    else:
        print(f"❌ Failed to send reply: {send_response.status_code}")
        print(send_response.text)
