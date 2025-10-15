import re
from playwright.sync_api import Playwright, sync_playwright, expect

def navigatePage(page, buttonName):
    # Navigate to Banking -> Process Bank Records
    page.locator("div").filter(has_text=re.compile(r"^Cash Book$")).first.click()
    button = page.get_by_role("link", name=buttonName)
    button.hover()
    page.wait_for_timeout(1000)  # wait 1 second
    button.click()