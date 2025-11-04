import re
from playwright.sync_api import Playwright, sync_playwright, expect
import RaasPlus
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

def run_extract_reconcile(
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
        context = browser.new_context(no_viewport=True, accept_downloads=True)
        page = context.new_page()
        # Login
        if website_url and username and password:
            functions.login(page, website_url, username, password)
        else:
            functions.login(page)
        page.wait_for_timeout(2000)
        functions.navigatePage(page, "Reconciliation Statements")
        page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_insert div").first.click()
        page.wait_for_timeout(5000)
        frame = page.frame(name="main")
        type_and_select(frame, accountName, "#ctl00_phF_form_t0_edCashAccountID_text")
        # today = datetime.today()
        # one_month_ago = today - relativedelta(months=1)
        # formatted_date = one_month_ago.strftime("%d/%m/%Y")
        # functions.log_message(webhook_url, formatted_date)
        date_box = frame.get_by_label("Load Documents Up To:")
        date_box.click()
        date_box.type(date, delay=100)
        statement_balance_box = frame.get_by_label("Statement Balance:")
        statement_balance_box.click()
        statement_balance_box.fill(str(amount))
        # click reconcile processed button
        frame.locator("#ctl00_phG_tab_t0_grid1_at_tlb_ul > li:nth-child(14)").click()
        frame.locator("#ctl00_phG_tab_t0_grid1_at_tlb_menuhi_item_0").nth(0).click()
        page.wait_for_timeout(15000)

        # set reconciled to false
        header = frame.locator("#ctl00_phG_tab_t0_grid1_headerT tr td:nth-child(2)")
        header.wait_for(state="visible", timeout=15000)
        header.click()
        frame.get_by_text("False").click()
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
        run_extract_reconcile(
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