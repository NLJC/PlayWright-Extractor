import re
import config
from playwright.sync_api import Playwright, sync_playwright, expect
import pandas as pd
import polars as pl

def login(page, website_url, username, password):
    page.goto(website_url)
    dropdown = page.locator("#cmbCompany")  
    dropdown.select_option("DBKK UAT")  # by value or visible text
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    # page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Sign In").click()

def navigatePage(page, buttonName):
    # Navigate to Banking -> Process Bank Records
    page.locator("div").filter(has_text=re.compile(r"^Cash Book$")).first.click()
    button = page.get_by_role("link", name=buttonName)
    button.hover()
    page.wait_for_timeout(1000)  # wait 1 second
    button.click()
    page.wait_for_timeout(5000)  # wait 5 seconds

def log_message(webhook_url, message, extra=None):
    print(message)
    if webhook_url:
        payload = {"message": message}
        if extra is not None:
            if isinstance(extra, dict):
                payload.update(extra)
            else:
                payload["extra"] = extra
        try:
            requests.post(webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Webhook Error] {e}: {message}")

            import requests

def send_pingback(url, status, requests, payload=None, error=None):
    """
    Send a pingback to the specified URL with status, payload, and optional error.
    """
    if url:
        data = {"status": status, "payload": payload}
        if error:
            data["error"] = error
        try:
            requests.post(url, json=data, timeout=10)
        except Exception as e:
            print(f"Pingback failed: {e}")

def safe_read_excel(path: str) -> pd.DataFrame:
    """
    Read Excel safely without triggering openpyxl style errors.
    Uses polars, then converts back to pandas DataFrame.
    """
    try:
        df = pl.read_excel(path)   # polars ignores styles
        return df.to_pandas()
    except Exception as e:
        raise RuntimeError(f"❌ Failed to load Excel with polars: {e}")
    
def highlight(page, item):
    try:
        # Ensure element is attached first
        item.wait_for(state="attached", timeout=15000)

        # Scroll into view in case it's hidden
        item.scroll_into_view_if_needed(timeout=5000)

        # Ensure it's visible
        item.wait_for(state="visible", timeout=5000)

        # Add red border highlight
        item.evaluate("el => el.style.border = '3px solid red'")
        page.wait_for_timeout(300)  # quick flash
        item.evaluate("el => el.style.border = ''")

    except Exception as e:
        print(f"[WARN] Highlight failed: {e}")

def highlight_and_click(page, button):
    # highlight(page, button)
    try:
        button.click(force=True, timeout=5000)
    except Exception as e:
        print(f"[ERROR] Click failed: {e}")
    
def click_account_name(page, frame, accountName):
    # Click on the account name link
    frame.get_by_role("link", name=accountName).last.click()
    page.wait_for_timeout(1000)  # wait 1 second

def wait_for_iframe(page):
    # Wait until iframe is ready
    page.wait_for_selector("iframe[name='main']")
    frame = page.frame(name="main")
    return frame