import re
import config
from playwright.sync_api import Playwright, sync_playwright, expect

def login(page, website_url, username, password):
    page.goto(website_url)
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    # page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Sign In").click()
