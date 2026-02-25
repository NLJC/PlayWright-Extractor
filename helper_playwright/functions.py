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
    # Check if dropdown selection is enabled in .env (default to True if not set)
    # The user specifically requested to skip this if set to false
    if os.getenv("dropdown_selector", "true").lower() == "true":
        dropdown = page.locator("#cmbCompany")  
        dropdown.select_option("DBKK UAT")  # by value or visible text
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    # page.get_by_role("button", name="Next").click()
    # Click "Sign In" or "Next" depending on what is displayed
    # We use a regex to match either case insensitive
    page.get_by_role("button", name=re.compile(r"Sign In|Next", re.IGNORECASE)).click()

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

def smart_click(page, locator, description: str = "element", timeout: int = 10000, page_wait_time: int = 15000):
    """Click with multiple fallback strategies."""
    try:
        locator.wait_for(state="visible", timeout=timeout)
        locator.click(timeout=page_wait_time)
        return True
    except:
        try:
            locator.click(force=True, timeout=page_wait_time)
            return True
        except:
            try:
                locator.evaluate("el => el.click()")
                return True
            except Exception as e:
                print(f"[ERROR] All click strategies failed for {description}")
                return False

def is_table_empty(rows) -> bool:
    """Check if table has any meaningful data."""
    row_count = rows.count()
    for i in range(row_count):
        row_text = rows.nth(i).inner_text().strip()
        if row_text and row_text not in ["0.00\n0.00", "No records found", ""]:
            return False
    return True

def smart_wait_for_page_load(page, page_wait_time: int = 15000, additional_check=None):
    """
    Smart wait that proceeds as soon as page is ready instead of waiting full duration.
    """
    try:
        # Wait for network to be idle
        page.wait_for_load_state("networkidle", timeout=page_wait_time)

        # If additional check provided, wait for it with polling
        if additional_check:
            start_time = page.evaluate("Date.now()")
            while True:
                if additional_check():
                    break
                current_time = page.evaluate("Date.now()")
                if current_time - start_time > page_wait_time:
                    break
                page.wait_for_timeout(200)  # Poll every 200ms

        # Small buffer to ensure stability
        page.wait_for_timeout(500)

    except Exception as e:
        # If smart wait fails, fall back to simple timeout
        page.wait_for_timeout(page_wait_time)

def filter_table(frame, header_text: str, textbox_selector: str, value: str, page_wait_time: int = 15000):
    """Filter table by clicking header and entering value."""
    try:
        header = frame.locator("td.GridHeader.GridRow", has_text=header_text).first
        textbox = frame.locator(textbox_selector)
        
        # Click header
        smart_click(None, header, f"{header_text} header", page_wait_time=page_wait_time)
        
        # Wait for textbox
        try:
            textbox.wait_for(state="visible", timeout=page_wait_time)
        except:
            smart_click(None, header, f"{header_text} header (retry)", page_wait_time=page_wait_time)
            textbox.wait_for(state="visible", timeout=page_wait_time)
        
        if not textbox.is_visible():
            return
        
        # Fill and apply filter
        contains_button = frame.get_by_text("Contains", exact=True).first
        if contains_button.count() > 0:
            smart_click(None, contains_button, "Contains button", page_wait_time=page_wait_time)
            
        smart_click(None, textbox, f"{header_text} textbox", page_wait_time=page_wait_time)
        textbox.fill(str(value))
        
        ok_button = frame.get_by_role("button", name="OK").first
        smart_click(None, ok_button, "OK button", page_wait_time=page_wait_time)

        # Smart wait for filter to apply
        smart_wait_for_page_load(frame.page, page_wait_time=page_wait_time)
        
    except Exception as e:
        print(f"[ERROR] Filter failed for '{header_text}': {e}")

def wait_for_iframe(page):
    # Wait until iframe is ready
    page.wait_for_selector("iframe[name='main']")
    frame = page.frame(name="main")
    return frame