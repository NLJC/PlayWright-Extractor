"""
Extract Reconciliation Statement - Optimized Version
====================================================
This module handles the automated extraction of reconciliation statements with improved
robustness, error handling, and efficiency.

Key Improvements:
- Intelligent waiting strategies (reduced fixed timeouts)
- Better error handling with retry logic
- Cleaner separation of concerns
- Enhanced logging
- Clear step labeling
"""

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd
import requests
from dateutil.relativedelta import relativedelta
from dotenv import load_dotenv
from playwright.sync_api import Playwright, expect, sync_playwright

from helper_playwright import functions
from helper_playwright.email_reply import reply_to_trigger_email
from helper_playwright.paths import get_downloads_dir
from . import RaasPlus

# Load environment variables
load_dotenv()


class ReconciliationExtractor:
    """Handles reconciliation statement extraction with improved robustness."""
    
    def __init__(
        self,
        playwright: Playwright,
        account_name: str,
        date: str,
        amount: float,
        save_path: str,
        website_url: str = None,
        username: str = None,
        password: str = None,
        pingback_url: str = None,
        payload: dict = None,
        webhook_url: str = None,
        headless: bool = False
    ):
        self.playwright = playwright
        self.account_name = account_name
        self.date = date
        self.amount = amount
        self.save_path = save_path
        self.website_url = website_url or os.getenv("WEBSITE_URL")
        self.username = username or os.getenv("WEBSITE_USERNAME")
        self.password = password or os.getenv("PASSWORD")
        self.pingback_url = pingback_url
        self.payload = payload
        self.webhook_url = webhook_url
        self.headless = headless
        self.download_dir = str(get_downloads_dir())
        
        self.browser = None
        self.context = None
        self.page = None
        self.frame = None
        
    def log(self, message: str, level: str = "info"):
        """Centralized logging with webhook support."""
        print(f"[{level.upper()}] {message}")
        if self.webhook_url:
            try:
                requests.post(
                    self.webhook_url,
                    json={"message": message, "level": level},
                    timeout=5
                )
            except Exception as e:
                print(f"[WARN] Webhook logging failed: {e}")
    
    def send_pingback(self, status: str, error: str = None):
        """Send status update to pingback URL."""
        if self.pingback_url:
            data = {"status": status, "payload": self.payload}
            if error:
                data["error"] = error
            try:
                requests.post(self.pingback_url, json=data, timeout=5)
                self.log(f"Pingback sent: {status}", "debug")
            except Exception as e:
                self.log(f"Failed to send pingback: {e}", "warning")
    
    def initialize_browser(self):
        """STEP 1: Initialize browser."""
        self.log("=" * 60)
        self.log("STEP 1: Initializing browser...")
        self.log("=" * 60)
        
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        
        # Video Recording Setup
        record_video = os.getenv("RECORD_VIDEO", "false").lower() == "true"
        save_dir = os.getenv("SAVE_DIRECTORY")
        
        if record_video and save_dir:
            video_dir = Path(save_dir) / "outputs" / "recording"
            video_dir.mkdir(parents=True, exist_ok=True)
            self.log(f"[INFO] Video recording enabled. Saving to: {video_dir}")
            
            self.context = self.browser.new_context(
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 720},
                viewport={"width": 1280, "height": 720},
                accept_downloads=True
            )
        else:
            self.context = self.browser.new_context(
                viewport={"width": 1280, "height": 720},
                accept_downloads=True
            )
            
        self.page = self.context.new_page()
        self.log("[OK] Browser initialized successfully")

    def cleanup(self):
        """Clean up browser resources."""
        try:
            if self.context:
                # Capture video path if recording
                video_source_path = None
                try:
                    if self.page:
                        video = self.page.video
                        if video:
                            video_source_path = video.path()
                except:
                    pass

                self.context.close()  # Important for saving video
                self.context = None

                # Rename video if it exists
                if video_source_path and os.path.exists(video_source_path):
                    try:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        folder = os.path.dirname(video_source_path)
                        new_path = os.path.join(folder, f"extract_reconcile_{timestamp}.webm")
                        os.rename(video_source_path, new_path)
                        self.log(f"[INFO] Video saved: {new_path}")
                    except Exception as e:
                        self.log(f"[WARNING] Video rename failed: {e}", "warning")

            if self.browser:
                self.browser.close()
            self.log("Browser cleanup completed")
        except Exception as e:
            self.log(f"Cleanup error: {e}", "warning")
    
    def wait_for_iframe(self, timeout: int = 20000):
        """Wait for and return the main iframe."""
        try:
            self.page.wait_for_selector("iframe[name='main']", timeout=timeout)
            frame = self.page.frame(name="main")
            if frame is None:
                raise Exception("Frame is None after waiting")
            return frame
        except Exception as e:
            self.log(f"Failed to get iframe: {e}", "error")
            raise
    
    def smart_click(self, locator, description: str = "element", timeout: int = 10000):
        """Click with multiple fallback strategies."""
        try:
            locator.wait_for(state="visible", timeout=timeout)
            locator.click(timeout=5000)
            self.log(f"Clicked {description}")
            return True
        except:
            try:
                locator.click(force=True, timeout=5000)
                self.log(f"Force clicked {description}")
                return True
            except:
                try:
                    locator.evaluate("el => el.click()")
                    self.log(f"JS clicked {description}")
                    return True
                except Exception as e:
                    self.log(f"All click strategies failed for {description}: {e}", "error")
                    return False
    
    def type_and_select_account(self, cash_account: str):
        """STEP 4: Type and select cash account from dropdown."""
        self.log("=" * 60)
        self.log(f"STEP 4: Selecting cash account: {cash_account}")
        self.log("=" * 60)
        
        locator = "#ctl00_phF_form_t0_edCashAccountID_text"
        textbox = self.frame.locator(locator)
        
        # Click and type
        self.smart_click(textbox, "Cash Account textbox")
        textbox.type(cash_account)
        
        # Build regex pattern and select
        pattern = rf"^{re.escape(cash_account)}\b"
        self.frame.locator(f"text=/{pattern}/").first.click()
        
        self.log(f"✅ Selected account: {cash_account}")
    
    def enter_date_and_balance(self):
        """STEP 5: Enter date and statement balance."""
        self.log("=" * 60)
        self.log(f"STEP 5: Entering date ({self.date}) and balance ({self.amount})")
        self.log("=" * 60)
        
        # Enter date
        date_box = self.frame.get_by_label("Load Documents Up To:")
        self.smart_click(date_box, "Date box")
        date_box.type(self.date, delay=100)
        self.page.keyboard.press("Enter")
        self.log(f"✅ Entered date: {self.date}")
        
        # Enter balance
        balance_box = self.frame.get_by_label("Statement Balance:")
        self.smart_click(balance_box, "Statement Balance box")
        balance_box.fill(str(self.amount))
        self.page.keyboard.press("Enter")
        self.log(f"✅ Entered balance: {self.amount}")
    
    def click_reconcile_processed(self):
        """STEP 6: Click Reconcile Processed button."""
        self.log("=" * 60)
        self.log("STEP 6: Clicking Reconcile Processed button")
        self.log("=" * 60)
        
        toolbar = self.frame.locator("#ctl00_phG_tab_t0_grid1_at_tlb_ul").first
        toolbar.wait_for(state="visible", timeout=15000)
        
        button_candidates = toolbar.locator("div.toolBtnNormal").filter(
            has_text=re.compile(r"^\s*Reconcile Processed\s*$", re.IGNORECASE)
        )
        button_candidates.wait_for(state="visible", timeout=15000)
        
        reconcile_btn = button_candidates.first
        button_text = reconcile_btn.inner_text().strip()
        
        if button_text.lower() != "reconcile processed":
            raise Exception(f"Expected 'Reconcile Processed' but saw '{button_text}'")
        
        reconcile_btn.scroll_into_view_if_needed()
        self.smart_click(reconcile_btn, "Reconcile Processed button")
        self.page.wait_for_timeout(15000)
        
        self.log("✅ Reconcile Processed clicked")
    
    def filter_by_reconciled_false(self):
        """STEP 7: Filter Reconciled column by False."""
        self.log("=" * 60)
        self.log("STEP 7: Filtering Reconciled column by False")
        self.log("=" * 60)
        
        # Locate visible Reconciled header
        headers = self.frame.locator("td.GridHeader.GridRow", has_text="Reconciled")
        count = headers.count()
        self.log(f"Found {count} possible Reconciled headers")
        
        header = None
        for i in range(count):
            h = headers.nth(i)
            if h.is_visible():
                header = h
                self.log(f"Using visible header #{i}")
                break
        
        if header is None:
            raise Exception("Could not locate visible Reconciled header")
        
        # Force click with mouse events
        self.log("Forcing JS click with full mouse events...")
        header.evaluate("""
        (el) => {
            ['mouseover','mousedown','mouseup','click'].forEach(ev => {
                el.dispatchEvent(new MouseEvent(ev, { bubbles: true, cancelable: true }));
            });
        }
        """)
        self.page.wait_for_timeout(1500)
        
        # Click False from popup
        false_button = self.frame.get_by_text("False", exact=True)
        try:
            false_button.first.wait_for(timeout=5000)
            false_button.first.click()
            self.log("✅ Filtered by False")
        except:
            raise Exception("Filter popup did not appear")
        
        self.frame.get_by_role("button", name="OK").click()
        self.page.wait_for_timeout(5000)
    
    def filter_by_cleared_false(self):
        """STEP 8: Filter Cleared column by False."""
        self.log("=" * 60)
        self.log("STEP 8: Filtering Cleared column by False")
        self.log("=" * 60)
        
        header = self.frame.locator("#ctl00_phG_tab_t0_grid1_headerT tr td:nth-child(3)")
        header.wait_for(state="visible", timeout=15000)
        header.click()
        
        self.frame.get_by_text("False").click()
        self.frame.get_by_role("button", name="OK").click()
        self.page.wait_for_timeout(5000)
        
        self.log("✅ Filtered Cleared by False")
    
    def export_to_excel(self) -> str:
        """STEP 9: Export filtered data to Excel."""
        self.log("=" * 60)
        self.log("STEP 9: Exporting to Excel")
        self.log("=" * 60)
        
        # First, check if Export Excel button is directly visible
        # We need to be specific because there are multiple ExportExcel buttons on the page
        # Based on logs, the correct one is #ctl00_phG_tab_t0_grid1_menu_item_7
        
        # Try specific ID first (most reliable based on logs)
        export_direct = self.frame.locator('#ctl00_phG_tab_t0_grid1_menu_item_7')
        
        if export_direct.count() > 0 and export_direct.is_visible():
            self.log("✅ Export Excel button is directly visible (found by ID)")
        else:
            # Fallback: try generic selector but use .first to avoid strict mode violation
            export_direct = self.frame.locator('li[data-cmd="ExportExcel"].menuItem').first
            
            if export_direct.count() > 0 and export_direct.is_visible():
                 self.log("✅ Export Excel button is directly visible (found by class)")
            else:
                self.log("Export button not visible, clicking HiddenItems dropdown...")
                
                # Click the HiddenItems dropdown to reveal the Export button
                # We need to target the HiddenItems button in the correct tab (tab_t0_grid1)
                # Structure: <div class="toolsBtn" data-cmd="hi"> with icon="HiddenItems"
                
                # Try to find HiddenItems button in the correct grid
                hidden_items_button = self.frame.locator('#ctl00_phG_tab_t0_grid1_at_tlb_ul .toolsBtn[data-cmd="hi"]')
                
                if hidden_items_button.count() > 0:
                    self.log("Found HiddenItems button in tab_t0_grid1, clicking...")
                    self.smart_click(hidden_items_button, "HiddenItems dropdown (tab_t0_grid1)")
                    self.page.wait_for_timeout(1500)
                else:
                    # Fallback: try any HiddenItems button
                    hidden_items_button = self.frame.locator('.toolsBtn[data-cmd="hi"]')
                    if hidden_items_button.count() > 0:
                        self.log("Found HiddenItems button (fallback), clicking...")
                        self.smart_click(hidden_items_button.first, "HiddenItems dropdown (fallback)")
                        self.page.wait_for_timeout(1500)
                    else:
                        # Fallback: Look for button with HiddenItems icon
                        self.log("Trying alternative selector for HiddenItems...")
                        hidden_icon = self.frame.locator('.control-HiddenItems')
                        if hidden_icon.count() > 0:
                            # Click the parent button
                            parent_btn = hidden_icon.locator('xpath=ancestor::div[@class="toolsBtn"]').first
                            self.smart_click(parent_btn, "HiddenItems button (via icon)")
                            self.page.wait_for_timeout(1500)
                        else:
                            # Last resort: Try clicking any toolbar button with dropdown
                            self.log("Trying to find any dropdown button...")
                            dropdown_buttons = self.frame.locator('.toolBtnDD')
                            for i in range(dropdown_buttons.count()):
                                btn = dropdown_buttons.nth(i)
                                if btn.is_visible():
                                    self.log(f"Trying dropdown button {i}")
                                    self.smart_click(btn, f"Dropdown button {i}")
                                    self.page.wait_for_timeout(1500)
                                    
                                    # Check if Export button appeared
                                    # Use .first to avoid strict mode violation
                                    if self.frame.locator('li[data-cmd="ExportExcel"]').first.is_visible():
                                        self.log(f"✅ Export button appeared after clicking dropdown {i}")
                                        break
        
        # Wait for menu to fully render
        self.page.wait_for_timeout(1000)
        
        # Trigger download with increased timeout
        try:
            with self.page.expect_download(timeout=60000) as download_info:  # 60 second timeout
                # Click the Export Excel button
                clicked = False
                
                # Selector 1: Specific ID (Most reliable)
                try:
                    export_button = self.frame.locator('#ctl00_phG_tab_t0_grid1_menu_item_7')
                    if export_button.count() > 0 and export_button.is_visible():
                        self.log("✅ Found Export Excel button by specific ID")
                        self.smart_click(export_button, "Export Excel button (ID)")
                        clicked = True
                except Exception as e:
                    self.log(f"Selector 1 (ID) failed: {e}", "warning")
                
                # Selector 2: By data-cmd attribute with class filter
                if not clicked:
                    try:
                        # First try the enabled button (class="menuItem")
                        # IMPORTANT: Use .first to avoid strict mode violation if multiple exist
                        export_button = self.frame.locator('li[data-cmd="ExportExcel"].menuItem')
                        if export_button.count() > 0:
                            self.log(f"Found Export Excel button by data-cmd + menuItem class (count: {export_button.count()})")
                            if export_button.first.is_visible():
                                self.log("✅ Export Excel button is visible, clicking...")
                                self.smart_click(export_button.first, "Export Excel button (menuItem)")
                                clicked = True
                            else:
                                self.log("Export button found but not visible", "warning")
                    except Exception as e:
                        self.log(f"Selector 2 (data-cmd + class) failed: {e}", "warning")
                
                # Selector 3: By menu item ID (if it has one)
                if not clicked:
                    try:
                        # Try common menu item IDs
                        for item_id in ["item_7", "item_3", "item_5"]:
                            export_button = self.frame.locator(f'li[id*="{item_id}"][data-cmd="ExportExcel"]')
                            if export_button.count() > 0 and export_button.first.is_visible():
                                self.log(f"Found export button using menu item ID: {item_id}")
                                self.smart_click(export_button.first, f"Export Excel button ({item_id})")
                                clicked = True
                                break
                    except Exception as e:
                        self.log(f"Selector 3 (menu ID) failed: {e}", "warning")
                
                # Selector 4: By Excel icon class
                if not clicked:
                    try:
                        excel_icon = self.frame.locator('.main-Excel')
                        if excel_icon.count() > 0:
                            self.log(f"Found Excel icon (count: {excel_icon.count()})")
                            # Click the parent li element
                            parent_li = excel_icon.locator('xpath=ancestor::li[@class="menuItem"]').first
                            if parent_li.count() > 0 and parent_li.is_visible():
                                self.log("Clicking parent li of Excel icon")
                                self.smart_click(parent_li, "Export Excel button (via icon)")
                                clicked = True
                    except Exception as e:
                        self.log(f"Selector 4 (Excel icon) failed: {e}", "warning")
                
                # Selector 5: By text "Export" in menu items
                if not clicked:
                    try:
                        menu_items = self.frame.locator('li.menuItem')
                        self.log(f"Found {menu_items.count()} menu items")
                        for i in range(menu_items.count()):
                            item = menu_items.nth(i)
                            if item.is_visible():
                                item_text = item.inner_text().strip()
                                self.log(f"Menu item {i}: '{item_text}'")
                                if "export" in item_text.lower():
                                    # Check if it has Excel icon
                                    has_excel = item.locator('.main-Excel').count() > 0
                                    if has_excel:
                                        self.log(f"✅ Found Export with Excel icon at item {i}")
                                        self.smart_click(item, f"Export Excel menu item {i}")
                                        clicked = True
                                        break
                    except Exception as e:
                        self.log(f"Selector 5 (menu items) failed: {e}", "warning")
                
                if not clicked:
                    raise Exception("Could not find Export to Excel button after trying all selectors")
            
            # Save download
            download = download_info.value
            filename = download.suggested_filename
            self.log(f"Download started: {filename}")
            
            reconciliation_save_path = os.path.join(self.download_dir, filename)
            
            # Ensure directory exists
            os.makedirs(os.path.dirname(reconciliation_save_path), exist_ok=True)
            
            download.save_as(reconciliation_save_path)
            self.log(f"✅ File saved to: {reconciliation_save_path}")
            
            # Verify file exists
            if not os.path.exists(reconciliation_save_path):
                raise FileNotFoundError(f"Downloaded file not found at {reconciliation_save_path}")
            
            return reconciliation_save_path
            
        except Exception as e:
            self.log(f"Download failed: {e}", "error")
            self.log("Attempting alternative download method...", "warning")
            
            # Alternative: Try clicking the dropdown again and finding the button
            self.page.wait_for_timeout(2000)
            
            # Try to find any visible Excel export option
            excel_options = self.frame.locator("text=/excel/i")
            if excel_options.count() > 0:
                self.log(f"Found {excel_options.count()} Excel options")
                for i in range(excel_options.count()):
                    option = excel_options.nth(i)
                    if option.is_visible():
                        self.log(f"Trying Excel option {i}")
                        try:
                            with self.page.expect_download(timeout=60000) as download_info:
                                self.smart_click(option, f"Excel option {i}")
                            
                            download = download_info.value
                            filename = download.suggested_filename
                            reconciliation_save_path = os.path.join(self.download_dir, filename)
                            
                            # Ensure directory exists
                            os.makedirs(os.path.dirname(reconciliation_save_path), exist_ok=True)
                            
                            download.save_as(reconciliation_save_path)
                            self.log(f"✅ File saved to: {reconciliation_save_path}")
                            return reconciliation_save_path
                        except:
                            continue
            
            raise Exception("Failed to download Excel file after all attempts")
    
    def calculate_unmatched_statement(self):
        """STEP 10: Calculate unmatched statement."""
        self.log("=" * 60)
        self.log("STEP 10: Calculating unmatched statement")
        self.log("=" * 60)
        
        # Click unmatched statement tab
        unmatched_tab = self.frame.locator("#ctl00_phG_tab_tab1")
        self.smart_click(unmatched_tab, "Unmatched Statement tab")
        
        # Click calculate button
        calculate_button = self.frame.locator(
            "#ctl00_phG_tab_t1_grid2_at_tlb_ul > li:nth-child(3) > div > div"
        )
        self.smart_click(calculate_button, "Calculate button")
        self.page.wait_for_timeout(20000)
        
        self.log("✅ Unmatched statement calculated")
    
    def save_reconciliation(self):
        """STEP 11: Save reconciliation statement."""
        self.log("=" * 60)
        self.log("STEP 11: Saving reconciliation statement")
        self.log("=" * 60)
        
        save_button = self.frame.locator(
            "#ctl00_phDS_ds_ToolBar_Save > div > qp-hyper-icon > div > div > div"
        )
        
        if save_button.is_enabled():
            self.log("Save button is active - clicking...")
            self.smart_click(save_button, "Save button")
            self.log("✅ Reconciliation saved")
        else:
            self.log("⚠️ Save button is disabled - skipping", "warning")
    
    def run(self) -> list:
        """
        Main execution method - orchestrates the entire extraction process.
        Returns list of processed records.
        """
        reconciliation_save_path = None
        
        try:
            self.send_pingback("started")
            self.log("=" * 60)
            self.log("EXTRACT RECONCILIATION STATEMENT - OPTIMIZED VERSION")
            self.log("=" * 60)
            
            # STEP 1: Initialize browser
            self.initialize_browser()
            
            # STEP 2: Login
            self.log("=" * 60)
            self.log("STEP 2: Logging in...")
            self.log("=" * 60)
            functions.login(self.page, self.website_url, self.username, self.password)
            self.page.wait_for_timeout(2000)
            self.log("✅ Login successful")
            
            # STEP 3: Navigate to Reconciliation Statements
            self.log("=" * 60)
            self.log("STEP 3: Navigating to Reconciliation Statements")
            self.log("=" * 60)
            functions.navigatePage(self.page, "Reconciliation Statements")
            
            # Click insert/new button
            self.page.locator("iframe[name=\"main\"]").content_frame.locator(
                "#ctl00_phDS_ds_ToolBar_insert div"
            ).first.click()
            self.page.wait_for_timeout(10000)
            
            self.frame = self.wait_for_iframe()
            self.log("✅ Navigation successful")
            
            # STEP 4: Select cash account
            self.type_and_select_account(self.account_name)
            
            # STEP 5: Enter date and balance
            self.enter_date_and_balance()
            
            # STEP 6: Click Reconcile Processed
            self.click_reconcile_processed()
            
            # STEP 7: Filter by Reconciled = False
            self.filter_by_reconciled_false()
            
            # STEP 8: Filter by Cleared = False
            self.filter_by_cleared_false()
            
            # STEP 9: Export to Excel
            reconciliation_save_path = self.export_to_excel()
            
            # STEP 10: Calculate unmatched statement
            self.calculate_unmatched_statement()
            
            # STEP 11: Save reconciliation
            self.save_reconciliation()
            
            # Cleanup browser
            self.cleanup()
            
            # Send success notification
            self.send_pingback("completed")
            
            # Send email notification
            try:
                reply_to_trigger_email("✅ Extract Reconciliation Statement completed successfully.")
            except Exception as e:
                self.log(f"Email notification failed: {e}", "warning")
            
            # Load and return data
            self.log("=" * 60)
            self.log("STEP 12: Loading extracted data")
            self.log("=" * 60)
            df = functions.safe_read_excel(reconciliation_save_path)
            self.log(f"✅ Loaded {len(df)} records")
            
            # STEP 13: Chain to RaasPlus
            self.log("=" * 60)
            self.log("STEP 13: Chaining to RaasPlus process")
            self.log("=" * 60)
            RaasPlus.run_RaasPlus(
                self.playwright,
                reconciliation_save_path,
                self.save_path,
                website_url=self.website_url,
                username=self.username,
                password=self.password,
                accountName=self.account_name,
                pingback_url=self.pingback_url,
                payload=self.payload,
                webhook_url=self.webhook_url,
                headless=self.headless
            )
            
            self.log("=" * 60)
            self.log("EXTRACT RECONCILIATION STATEMENT COMPLETED SUCCESSFULLY")
            self.log("=" * 60)
            
            return df.to_dict(orient="records")
            
        except Exception as e:
            self.log(f"FATAL ERROR: {e}", "error")
            self.send_pingback("failed", str(e))
            
            # Send failure email
            try:
                reply_to_trigger_email(f"❌ Extract Reconciliation Statement failed: {str(e)}")
            except:
                pass
            
            # Cleanup on error
            self.cleanup()
            
            raise


# Convenience function for backward compatibility
def extract_reconciliation_statements(
    playwright: Playwright,
    accountName: str,
    date: str,
    amount: float,
    save_path: str,
    website_url: str = None,
    username: str = None,
    password: str = None,
    pingback_url: str = None,
    payload: dict = None,
    webhook_url: str = None,
    headless: bool = False
) -> list:
    """
    Extract reconciliation statements with automation.
    
    Args:
        playwright: Playwright instance
        accountName: Name of the cash account
        date: Date for reconciliation (format: DD/MM/YYYY)
        amount: Statement balance amount
        save_path: Path to the bank transactions file
        website_url: Website URL (defaults to env var)
        username: Login username (defaults to env var)
        password: Login password (defaults to env var)
        pingback_url: Optional URL for status callbacks
        payload: Optional payload for pingback
        webhook_url: Optional URL for logging webhooks
        headless: Run browser in headless mode (default: False)
    
    Returns:
        List of extracted reconciliation records
    """
    extractor = ReconciliationExtractor(
        playwright=playwright,
        account_name=accountName,
        date=date,
        amount=amount,
        save_path=save_path,
        website_url=website_url,
        username=username,
        password=password,
        pingback_url=pingback_url,
        payload=payload,
        webhook_url=webhook_url,
        headless=headless
    )
    
    return extractor.run()


# Main execution
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
