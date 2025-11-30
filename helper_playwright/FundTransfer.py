from playwright.sync_api import Playwright, sync_playwright, expect
import functions
import requests
import pandas as pd
from dotenv import load_dotenv
import os
import re

def fill_textbox(frame, locator: str, text: str):
    frame.locator(locator).click()
    frame.locator(locator).type(text)
    frame.keyboard.press("Enter")

def type_and_select(frame, cashAccount: str, locator: str):
    # Fill in the textbox
    frame.locator(locator).click()
    frame.locator(locator).type(cashAccount)
    
    # Build regex pattern safely from variable
    pattern = rf"^{re.escape(cashAccount)}\b"

    # Click the first matching option from the dropdown
    frame.locator(f"text=/{pattern}/").first.click()

def wait_for_confirmation(page, frame):
    try:
        # --- Step 0: Wait up to 5s for the popup to appear ---
        print("⏳ Waiting for confirmation popup...")
        popup_visible = frame.locator("span.qp-lr-message").wait_for(state="visible", timeout=5000)
    except Exception:
        print("⚠️ No confirmation popup appeared within 5s — skipping confirmation wait.")
        return  # Exit early if popup never appeared

    try:
        # Define the main message element
        status_msg = frame.locator("span.qp-lr-message")

        # --- Step 1: Check for "Nothing in progress" first ---
        try:
            expect(status_msg).to_have_text("Nothing in progress", timeout=10000)
            print("⚠️  Status shows 'Nothing in progress' — Auto-Match may not have started.")
            functions.highlight(page, status_msg)
        except Exception:
            # If "Nothing in progress" not found, proceed as usual
            pass

        # --- Step 2: Wait for execution if it happens ---
        try:
            abort_message = frame.get_by_text("Executing. Press to abort")
            functions.highlight(page, abort_message)
            abort_message.wait_for(state="detached", timeout=180000)
            print("⏳ Auto-Match process finished executing.")
        except Exception:
            print("⚠️  No 'Executing' message appeared — continuing anyway.")

        # --- Step 3: Wait for the final success message ---
        try:
            success_msg = frame.locator("span.qp-lr-message")
            expect(success_msg).to_have_text("The operation has completed.", timeout=180000)
            functions.highlight(page, success_msg)
            print("✅ Operation completed successfully!")
        except Exception:
            print("⚠️ No 'Operation completed' message found — continuing anyway.")

    except Exception as e:
        print(f"⚠️ Error while waiting for confirmation: {e}")
        # Just skip instead of raising exception
        return

def run_internal_transfer(
    playwright: Playwright, 
    file, 
    website_url=os.getenv("WEBSITE_URL"), 
    username=os.getenv("USERNAME"), 
    password=os.getenv("PASSWORD"),
    pingback_url=None,
    payload=None,
    webhook_url=None
) -> None:

    # ============================================================
    # ✅ PINGBACK
    # ============================================================
    functions.send_pingback(pingback_url, "started", requests=requests, payload=payload)

    # ============================================================
    # ✅ LOAD EXCEL + FILTER INTERNAL TRANSFER ROWS
    # ============================================================
    print(f"📄 Loading internal transfer file: {file}")

    df = pd.read_excel(file, dtype=str)
    df.columns = [c.strip() for c in df.columns]

    required_cols = [
        "Tran. Code",
        "Ext Ref Num",
        "Bank Disbursement",
        "Transaction Date"
    ]

    for col in required_cols:
        if col not in df.columns:
            raise Exception(f"❌ Excel missing required column: {col}")

    # Filter rows ending with 6500
    df["Tran. Code"] = df["Tran. Code"].astype(str)
    filtered = df[df["Tran. Code"].str.endswith("6500", na=False)]

    if filtered.empty:
        print("⚠️ No internal transfer rows ending with 6500 found. Exiting.")
        functions.send_pingback(pingback_url, "completed", requests=requests, payload=payload)
        return

    filtered["Bank Disbursement"] = (
        filtered["Bank Disbursement"].str.replace(",", "", regex=False).astype(float)
    )

    print(f"✅ Found {len(filtered)} internal transfer entries")

    # ============================================================
    # ✅ OPEN BROWSER
    # ============================================================
    browser = playwright.chromium.launch(headless=False)

    context = browser.new_context(
        accept_downloads=True
    )

    page = context.new_page()

    # Login
    functions.login(page, website_url, username, password)

    # Navigate to internal transfer page
    functions.navigatePage(page, "New Transfer")

    # ============================================================
    # ✅ PROCESS EACH TRANSFER ENTRY
    # ============================================================
    for index, row in filtered.iterrows():
        ext_ref = row["Ext Ref Num"]
        amount = row["Bank Disbursement"]
        date = row["Transaction Date"]

        print(f"➡️ Processing internal transfer: ref={ext_ref}, Amount={amount}, Date={date}")

        try:
            type_and_select(frame=page.frame_locator("iframe"), cashAccount="MBB02", locator="#ctl00_phF_form_t0_edOutAccountID_text")
            type_and_select(frame=page.frame_locator("iframe"), cashAccount="MBB01", locator="#ctl00_phF_form_t0_edInAccountID_text")
            fill_textbox(frame=page.frame_locator("iframe"), locator="#ctl00_phF_form_t0_edOutExtRefNbr", text=ext_ref)
            fill_textbox(frame=page.frame_locator("iframe"), locator="#ctl00_phF_form_t0_edInExtRefNbr", text=ext_ref)
            fill_textbox(frame=page.frame_locator("iframe"), locator="#ctl00_phF_form_t0_edCuryTranOut", text=str(amount))
            fill_textbox(frame=page.frame_locator("iframe"), locator="#ctl00_phF_form_t0_edOutDate_text", text=str(date))
            fill_textbox(frame=page.frame_locator("iframe"), locator="#ctl00_phF_form_t0_edInDate_text", text=str(date))
            # click save
            page.locator("#ctl00_phDS_ds_ToolBar_Save > div").click()
            # click remove hold
            page.locator("#ctl00_phDS_ds_ToolBar_ReleaseFromHold > div").click()
            wait_for_confirmation(page, page.frame_locator("iframe"))
            # click release
            page.locator(text="RELEASE", type="button").click()
            wait_for_confirmation(page, page.frame_locator("iframe"))

            # --------------------------------------------------------
            # After submitting:
            # page.wait_for_timeout(2000)
            # --------------------------------------------------------

        except Exception as e:
            print(f"❌ Error processing transfer for Ref {ext_ref}: {e}")
            functions.log_message(webhook_url, f"❌ Failed transfer for {ext_ref}: {e}")

    # ============================================================
    # ✅ FINISH
    # ============================================================
    print("✅ All internal transfers processed")

    functions.send_pingback(pingback_url, "completed", requests=requests, payload=payload)

    browser.close()
