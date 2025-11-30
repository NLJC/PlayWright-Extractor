import re
import config
from playwright.sync_api import Playwright, sync_playwright, expect
import pandas as pd
import polars as pl
import logging
import os
import requests

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

class WebhookHandler(logging.Handler):
    """Custom log handler to send messages to a webhook URL."""
    def __init__(self, webhook_url):
        super().__init__()
        self.webhook_url = webhook_url

    def emit(self, record):
        try:
            log_entry = self.format(record)
            payload = {"message": log_entry}
            requests.post(self.webhook_url, json=payload, timeout=5)
        except Exception as e:
            print(f"[Webhook Error] {e}: {record.getMessage()}")
        
def setup_logger(name="main_logger", log_file="automation.log", webhook_url=None, level=logging.INFO):
    """Set up logger with console, file, and optional webhook output."""
    os.makedirs("logs", exist_ok=True)
    log_path = os.path.join("logs", log_file)

    logger = logging.getLogger(name)
    logger.setLevel(level)

    # avoid duplicate handlers
    if not logger.handlers:
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        logger.addHandler(ch)

        # File handler
        fh = logging.FileHandler(log_path, mode="a", encoding="utf-8")
        fh.setFormatter(formatter)
        logger.addHandler(fh)

        # Optional webhook handler
        if webhook_url:
            wh = WebhookHandler(webhook_url)
            wh.setFormatter(formatter)
            logger.addHandler(wh)

    return logger

def log_message(logger, message, level="info", extra=None):
    if extra:
        message = f"{message} | Extra: {extra}"

    # Log locally
    if level == "info":
        logger.info(message)
    elif level == "warning":
        logger.warning(message)
    elif level == "error":
        logger.error(message)
    else:
        logger.debug(message)

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