import re
from playwright.sync_api import Playwright, sync_playwright, expect
import functions
from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import pandas as pd
            
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
    website_url,
    username,
    password,
    accountName,
    save_path,
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
        today = datetime.today()
        one_month_ago = today - relativedelta(months=1)
        formatted_date = one_month_ago.strftime("%d/%m/%Y")
        functions.log_message(webhook_url, formatted_date)
        date_box = frame.get_by_label("Load Documents Up To:")
        date_box.click()
        date_box.type(formatted_date, delay=100)
        header = frame.locator("td.GridHeader.GridRow", has_text="Reconciled").nth(0)
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
        full_save_path = save_path + download.suggested_filename
        download.save_as(full_save_path)
        context.close()
        browser.close()
        functions.send_pingback(pingback_url, requests, "completed", payload)
        # Use safe_read_excel instead of pd.read_excel
        df = functions.safe_read_excel(full_save_path)
        return df.to_dict(orient="records")
    except Exception as e:
        functions.send_pingback(pingback_url, requests, "failed", payload, str(e))
        raise

if __name__ == "__main__":
    import config
    with sync_playwright() as playwright:
        run_extract_reconcile(
            playwright,
            accountName=config.accountName,
            save_path=config.save_path,
            website_url=config.website_url,
            username=config.username,
            password=config.password
        )