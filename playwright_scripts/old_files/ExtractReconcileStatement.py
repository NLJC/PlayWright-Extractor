import re
from playwright.sync_api import Playwright, sync_playwright, expect
from playwright_scripts import RaasPlus
import functions
from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import pandas as pd
from dotenv import load_dotenv
import os
from email_reply import reply_to_trigger_email

# Load the .env file
load_dotenv()
            
def type_and_select(frame, cashAccount: str, locator: str):
    # Fill in the textbox
    frame.locator(locator).click()
    frame.locator(locator).type(cashAccount)
    
    # Build regex pattern safely from variable
    pattern = rf"^{re.escape(cashAccount)}\b"

    # Click the first matching option from the dropdown
    frame.locator(f"text=/{pattern}/").first.click()

def get_reconciled_header(frame):
    headers = frame.locator("td.GridHeader.GridRow")

    for i in range(headers.count()):
        h = headers.nth(i)
        txt = h.inner_text().strip()

        # ✅ Must contain the label
        if "Reconciled" in txt:

            # ❌ Skip the phantom/hidden HS header
            id_attr = h.get_attribute("id") or ""
            if "_colHS_" in id_attr:
                continue

            # ✅ Only accept real colH header
            if "_colH_" in id_attr:
                return h

    return None

def force_click(locator):
    # Try normal click first
    try:
        locator.click(timeout=2000)
        return True
    except:
        pass

    # JS click as backup
    try:
        locator.evaluate("el => el.click()")
        return True
    except:
        pass

    # Full event-dispatch click
    try:
        locator.evaluate("""
            el => {
                const evt1 = new MouseEvent('mousedown', {bubbles: true});
                const evt2 = new MouseEvent('mouseup', {bubbles: true});
                const evt3 = new MouseEvent('click', {bubbles: true});
                el.dispatchEvent(evt1);
                el.dispatchEvent(evt2);
                el.dispatchEvent(evt3);
            }
        """)
        return True
    except:
        pass

    return False

def hover_and_click(page, locator):
    try:
        locator.wait_for(state="visible", timeout=8000)
    except:
        print("❌ Header not visible")
        return False

    try:
        print("🔍 Hovering Reconciled header...")
        locator.hover()
        page.wait_for_timeout(300)

        print("✅ Hover successful, attempting click...")
        locator.click(timeout=5000)
        return True

    except Exception:
        print("⚠️ Normal click failed, trying JS click...")

        try:
            locator.evaluate("el => el.click()")
            return True
        except Exception:
            print("❌ JS click also failed")
            return False

def extract_reconciliation_statements(
    playwright: Playwright,
    accountName: str,
    date: str,
    amount: float,
    save_path,
    website_url=os.getenv("WEBSITE_URL"),
    username=os.getenv("WEBSITE_USERNAME"),
    password=os.getenv("PASSWORD"),
    pingback_url=None,
    payload=None,
    webhook_url=None
):
    try:
        functions.send_pingback(pingback_url, requests, "started", payload)
        browser = playwright.chromium.launch(headless=False)
        context = browser.new_context(accept_downloads=True)
        page = context.new_page()
        # Login
        if website_url and username and password:
            functions.login(page, website_url, username, password)
        else:
            functions.login(page)
        page.wait_for_timeout(2000)
        functions.navigatePage(page, "Reconciliation Statements")
        page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_insert div").first.click()
        page.wait_for_timeout(10000)
        frame = page.frame(name="main")
        type_and_select(frame, accountName, "#ctl00_phF_form_t0_edCashAccountID_text")
        # today = datetime.today()
        # one_month_ago = today - relativedelta(months=1)
        # formatted_date = one_month_ago.strftime("%d/%m/%Y")
        # functions.log_message(webhook_url, formatted_date)
        date_box = frame.get_by_label("Load Documents Up To:")
        date_box.click()
        date_box.type(date, delay=100)
        page.keyboard.press("Enter")
        statement_balance_box = frame.get_by_label("Statement Balance:")
        statement_balance_box.click()
        statement_balance_box.fill(str(amount))
        page.keyboard.press("Enter")
        # click reconcile processed button using toolbar button text
        toolbar = frame.locator("#ctl00_phG_tab_t0_grid1_at_tlb_ul").first
        toolbar.wait_for(state="visible", timeout=15000)
        button_candidates = toolbar.locator("div.toolBtnNormal").filter(
            has_text=re.compile(r"^\s*Reconcile Processed\s*$", re.IGNORECASE)
        )
        button_candidates.wait_for(state="visible", timeout=15000)
        reconcile_btn = button_candidates.first
        button_text = reconcile_btn.inner_text().strip()
        if button_text.lower() != "reconcile processed":
            raise Exception(f"Expected 'Reconcile Processed' button but saw '{button_text}'")
        reconcile_btn.scroll_into_view_if_needed()
        reconcile_btn.click()
        page.wait_for_timeout(15000)

        # set reconciled to false
        # --- Locate real Reconciled header ---
        headers = frame.locator("td.GridHeader.GridRow", has_text="Reconciled")
        count = headers.count()

        print(f"🔎 Found {count} possible Reconciled headers")

        header = None

        for i in range(count):
            h = headers.nth(i)
            if h.is_visible():
                header = h
                print(f"✅ Using visible header #{i}")
                break

        if header is None:
            raise Exception("❌ Could not locate a visible Reconciled header!")

        # --- Force real click through overlay ---
        print("✅ Forcing JS click with full mouse events...")

        header.evaluate("""
        (el) => {
            ['mouseover','mousedown','mouseup','click'].forEach(ev => {
                el.dispatchEvent(new MouseEvent(ev, { bubbles: true, cancelable: true }));
            });
        }
        """)

        page.wait_for_timeout(1500)

        # --- Now click "False" from popup ---
        false_button = frame.get_by_text("False", exact=True)

        try:
            false_button.first.wait_for(timeout=5000)
            false_button.first.click()
            print("✅ Filtered by False")
        except:
            raise Exception("❌ Filter popup did not appear after clicking Reconciled header")
        
        frame.get_by_role("button", name="OK").click()
        page.wait_for_timeout(5000)
        # set cleared to false as well
        header = frame.locator("#ctl00_phG_tab_t0_grid1_headerT tr td:nth-child(3)")
        header.wait_for(state="visible", timeout=15000)
        header.click()
        frame.get_by_text("False").click()
        frame.get_by_role("button", name="OK").click()
        page.wait_for_timeout(5000)
        page.locator("iframe[name=\"main\"]").content_frame.locator("li:nth-child(14) > .toolsBtn > .toolBtnNormal").click()
        with page.expect_download() as download_info:
            frame.locator("text=Export to Excel").click()
        download = download_info.value
        functions.log_message(webhook_url, "✅ Download started:", download.suggested_filename)
        reconciliation_save_path = os.getenv("SAVE_DIRECTORY") + download.suggested_filename
        download.save_as(reconciliation_save_path)

        # click unmatched statement
        frame.locator("#ctl00_phG_tab_tab1").click()
        # click calculate unmatched statement
        frame.locator("#ctl00_phG_tab_t1_grid2_at_tlb_ul > li:nth-child(3) > div > div").click()
        page.wait_for_timeout(20000)
        #  click save
        save_button = frame.locator("#ctl00_phDS_ds_ToolBar_Save > div > qp-hyper-icon > div > div > div")

        # Check enabled state
        if save_button.is_enabled():
            functions.log_message(webhook_url, "💾 Save button is active → clicking it.")
            save_button.click()
        else:
            functions.log_message(webhook_url, "⚠️ Save button is disabled → skipping click.")

        context.close()
        browser.close()
        functions.send_pingback(pingback_url, requests, "completed", payload)
        reply_to_trigger_email("✅ Extract Reconciliation Statement completed successfully.")
        # Use safe_read_excel instead of pd.read_excel
        df = functions.safe_read_excel(reconciliation_save_path)

        RaasPlus.run_RaasPlus(
            playwright,
            reconciliation_save_path,
            save_path,
            website_url=website_url,
            username=username,
            password=password,
            accountName=accountName,
            pingback_url=pingback_url,
            payload=payload,
            webhook_url=webhook_url
        )

        return df.to_dict(orient="records")
    except Exception as e:
        functions.send_pingback(pingback_url, requests, "failed", payload, str(e))
        reply_to_trigger_email("Extract Reconciliation Statement failed.")
        raise

if __name__ == "__main__":
    import config
    with sync_playwright() as playwright:
        extract_reconciliation_statements(
            playwright=playwright,
            accountName=config.accountName,
            date="31/08/2024",
            amount=100.00,
            save_path=config.save_path,
            website_url=config.website_url,
            username=config.username,
            password=config.password,
            pingback_url=None,
            payload=None,
            webhook_url=None
        )
