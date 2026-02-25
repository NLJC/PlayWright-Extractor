"""
CA Match Process - Optimized Version
=====================================
This module handles the automated Cash Account matching process with improved
robustness, error handling, and efficiency.

Key Improvements:
- Intelligent waiting strategies (reduced fixed timeouts)
- Better error handling with retry logic
- Cleaner separation of concerns
- Improved pagination handling
- Enhanced logging
- Stale element prevention
"""

from datetime import datetime
from dateutil.relativedelta import relativedelta
from pathlib import Path
from typing import Optional, Tuple
import os
import time

import pandas as pd
import requests
from dotenv import load_dotenv
from playwright.sync_api import (
    Playwright,
    TimeoutError as PlaywrightTimeout,
    expect,
    sync_playwright,
)

from helper_playwright.functions import (
    login, navigatePage, wait_for_iframe, smart_click, 
    is_table_empty, smart_wait_for_page_load, filter_table,
    safe_read_excel
)
from helper_playwright.email_reply import reply_to_trigger_email
from helper_playwright.paths import get_downloads_dir
from . import ExtractReconcileStatement_Optimized as ExtractReconcileStatement
from logger import logger

# Load environment variables
load_dotenv()


class CAMatchProcessor:
    """Handles Cash Account matching automation with improved robustness."""
    
    def __init__(
        self,
        playwright: Playwright,
        account_name: str,
        date: str,
        amount: float,
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
        self.website_url = website_url or os.getenv("WEBSITE_URL")
        self.username = username or os.getenv("WEBSITE_USERNAME")
        self.password = password or os.getenv("PASSWORD")
        self.pingback_url = pingback_url
        self.payload = payload
        self.webhook_url = webhook_url
        self.headless = headless
        self.download_dir = str(get_downloads_dir())

    def log(self, message: str, level: str = "info"):
        """Wrapper around shared logger with safe level lookup."""
        log_fn = getattr(logger, level, logger.info)
        log_fn(message)

    def send_pingback(self, status: str, error: str = None):
        """Send a status pingback if configured."""
        if not self.pingback_url:
            return
        data = {"status": status, "account": self.account_name, "date": self.date, "amount": self.amount}
        if self.payload:
            data["payload"] = self.payload
        if error:
            data["error"] = error
        try:
            requests.post(self.pingback_url, json=data, timeout=10)
        except Exception as e:
            self.log(f"Pingback failed: {e}", "warning")

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
            if hasattr(self, 'context') and self.context:
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
                        new_path = os.path.join(folder, f"ca_match_process_{timestamp}.webm")
                        os.rename(video_source_path, new_path)
                        self.log(f"[INFO] Video saved: {new_path}")
                    except Exception as e:
                        self.log(f"[WARNING] Video rename failed: {e}", "warning")

            if hasattr(self, 'browser') and self.browser:
                self.browser.close()
            self.log("Browser cleanup completed")
        except Exception as e:
            self.log(f"Cleanup error: {e}", "warning")
    
    def wait_for_iframe(self, timeout: int = 20000) -> any:
        """Wait for and return the main iframe with retry logic."""
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
            # Strategy 1: Wait and normal click
            locator.wait_for(state="visible", timeout=timeout)
            locator.click(timeout=5000)
            self.log(f"Clicked {description} successfully")
            return True
        except Exception as e1:
            self.log(f"Normal click failed for {description}, trying force click...", "warning")
            try:
                # Strategy 2: Force click
                locator.click(force=True, timeout=5000)
                self.log(f"Force clicked {description}")
                return True
            except Exception as e2:
                self.log(f"Force click failed, trying JS click...", "warning")
                try:
                    # Strategy 3: JavaScript click
                    locator.evaluate("el => el.click()")
                    self.log(f"JS clicked {description}")
                    return True
                except Exception as e3:
                    self.log(f"All click strategies failed for {description}: {e3}", "error")
                    return False
    
    def wait_for_auto_match_completion(self):
        """
        Wait for auto-match operation to complete with intelligent detection.
        Handles various states: not started, executing, completed, or failed.
        """
        self.log("Waiting for auto-match confirmation...")
        
        try:
            # Wait for popup to appear (5s timeout)
            status_msg = self.frame.locator("span.qp-lr-message")
            status_msg.wait_for(state="visible", timeout=5000)
        except:
            self.log("No confirmation popup appeared - auto-match may not have started", "warning")
            return
        
        try:
            # Check for "Nothing in progress" state
            try:
                expect(status_msg).to_have_text("Nothing in progress", timeout=10000)
                self.log("Status shows 'Nothing in progress' - auto-match may not have started", "warning")
                return
            except:
                pass  # Expected if operation is running
            
            # Wait for execution phase
            try:
                abort_message = self.frame.get_by_text("Executing. Press to abort")
                abort_message.wait_for(state="visible", timeout=5000)
                self.log("Auto-match is executing...")
                abort_message.wait_for(state="detached", timeout=180000)
                self.log("Auto-match execution completed")
            except:
                self.log("No 'Executing' message detected", "warning")
            
            # Wait for completion message
            try:
                expect(status_msg).to_have_text("The operation has completed.", timeout=180000)
                self.log("âœ… Auto-match operation completed successfully!")
            except:
                self.log("No completion message found - continuing anyway", "warning")
                
        except Exception as e:
            self.log(f"Error during auto-match wait: {e}", "warning")
    
    def handle_detail_table(self) -> bool:
        """
        Handle detail table matching with support for Type A and Type B tables.
        Returns True if a match was processed, False otherwise.
        """
        # Try Type A table
        table_a = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
        # Try Type B table
        table_b = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")
        
        detail_table = None
        table_type = None
        
        # Detect table type
        try:
            table_a.wait_for(state="visible", timeout=3000)
            detail_table = table_a
            table_type = "A"
        except:
            try:
                table_b.wait_for(state="visible", timeout=3000)
                detail_table = table_b
                table_type = "B"
            except:
                self.log("âš ï¸ No detail table found", "warning")
                return False
        
        self.log(f"Found detail table Type {table_type}")
        
        # Process rows
        rows = detail_table.locator("tr")
        row_count = rows.count()
        self.log(f"Processing {row_count} rows in detail table")
        
        for j in range(row_count):
            row = rows.nth(j)
            relevance_cell = row.locator("td").nth(2)
            
            # Check visibility and extract relevance
            try:
                if not relevance_cell.is_visible():
                    continue
                relevance_text = relevance_cell.inner_text().strip()
            except Exception as e:
                self.log(f"Row {j} - relevance cell not accessible: {e}", "warning")
                continue
            
            # Parse relevance value
            try:
                relevance = float(relevance_text.replace(",", ""))
            except ValueError:
                self.log(f"Row {j} - invalid relevance value: {relevance_text}", "warning")
                continue
            
            self.log(f"Row {j} - relevance: {relevance}%")
            
            # Match if relevance >= 90%
            if relevance >= 90:
                checkbox_cell = row.locator("td").nth(1)
                self.log(f"âœ… Matching row {j} (Type {table_type}, relevance: {relevance}%)")
                
                if self.smart_click(checkbox_cell, f"checkbox in row {j}"):
                    # Wait for table to update
                    self.page.wait_for_timeout(2000)
                    return True
                else:
                    self.log(f"Failed to click checkbox in row {j}", "error")
                
                break  # Stop after first match
        
        return False

    
    def process_pagination_with_matching(self) -> int:
        """
        Process all pages with intelligent pagination and matching.
        Returns the total number of rows processed.
        """
        total_processed = 0
        page_num = 1
        
        while True:
            self.log(f"Processing page {page_num}...")
            
            try:
                # Wait for table to be ready
                self.frame.wait_for_selector(
                    "#ctl00_phG_PXSplitContainer_grid1_dataT0",
                    state="attached",
                    timeout=20000
                )
                
                # Get table and rows
                table = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
                rows = table.locator("tbody tr")
                row_count = rows.count()
                
                self.log(f"Found {row_count} rows on page {page_num}")
                
                # Process each row (skip last phantom row)
                for i in range(row_count - 1):
                    # Re-query row to avoid stale elements
                    row = rows.nth(i)
                    
                    try:
                        cols = row.locator("td")
                        col_count = cols.count()
                        
                        if col_count < 5:
                            self.log(f"Row {i} - insufficient columns ({col_count})", "warning")
                            continue
                        
                        # Extract Ext. Ref. Nbr. (5th column, index 4)
                        ext_ref_cell = cols.nth(4)
                        ext_ref = ext_ref_cell.inner_text().strip()
                        
                        # Skip header or empty rows
                        if not ext_ref or ext_ref == "Ext. Ref. Nbr.":
                            continue
                        
                        self.log(f"Row {i} - Ext. Ref. Nbr.: {ext_ref}")
                        
                        # Check match status (first column icons)
                        first_col = cols.nth(0)
                        icon_divs = first_col.locator("div")
                        icon_count = icon_divs.count()
                        
                        if icon_count == 0:
                            # Unmatched row - attempt to match
                            self.log(f"Row {i} - UNMATCHED, attempting to match...")
                            
                            # Click Ext. Ref. Nbr. to open detail view
                            if self.smart_click(ext_ref_cell, f"Ext. Ref. Nbr. in row {i}"):
                                self.page.wait_for_timeout(2000)
                                
                                # Handle detail table matching
                                matched = self.handle_detail_table()
                                if matched:
                                    self.log(f"Row {i} - Successfully matched!")
                                else:
                                    self.log(f"Row {i} - No suitable match found", "warning")
                            else:
                                self.log(f"Row {i} - Failed to open detail view", "error")
                        else:
                            self.log(f"Row {i} - Already matched, skipping")
                        
                        total_processed += 1
                        
                    except Exception as e:
                        self.log(f"Row {i} - Error processing: {e}", "error")
                        continue
                
                # Check for next page
                next_button = self.frame.locator(
                    "li:nth-child(4) > .toolsBtn > .toolBtnNormal .main-icon-img.main-PageNext"
                )
                
                if next_button.count() > 0 and next_button.is_visible():
                    self.log(f"Moving to page {page_num + 1}...")
                    if self.smart_click(next_button, "next page button"):
                        self.page.wait_for_timeout(2000)
                        page_num += 1
                    else:
                        self.log("Failed to click next button, stopping pagination", "warning")
                        break
                else:
                    self.log("No more pages - pagination complete")
                    break
                    
            except Exception as e:
                self.log(f"Error during pagination on page {page_num}: {e}", "error")
                break
        
        self.log(f"Pagination complete - processed {total_processed} total rows across {page_num} pages")
        return total_processed
    
    def perform_auto_match(self):
        """Execute the auto-match operation."""
        self.log("Starting auto-match process...")
        
        # Navigate to account
        self.frame = self.wait_for_iframe()
        account_link = self.frame.get_by_role("link", name=self.account_name).last
        self.smart_click(account_link, f"account link '{self.account_name}'")
        
        self.frame = self.wait_for_iframe()
        self.page.wait_for_timeout(5000)
        
        # Click Auto-Match button
        automatch_button = self.page.locator('iframe[name="main"]').content_frame.locator(
            "#ctl00_phDS_ds_ToolBar_AutoMatch"
        ).get_by_text("Auto-Match")
        
        self.smart_click(automatch_button, "Auto-Match button")
        self.frame = self.wait_for_iframe()
        self.page.wait_for_timeout(2000)
        
        # Wait for auto-match to complete
        self.wait_for_auto_match_completion()
        
        # Process matched items
        self.log("Processing auto-matched items...")
        process_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
            "#ctl00_phDS_ds_ToolBar_ProcessMatched"
        ).get_by_text("Process")
        self.smart_click(process_button, "Process button")
        self.page.wait_for_timeout(5000)
        
        # Go back
        back_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
            "#ctl00_phDS_ds_ToolBar_CancelCloseToList div"
        ).nth(3)
        self.smart_click(back_button, "Back button")
        self.page.wait_for_timeout(3000)
    
    def perform_manual_matching(self):
        """Perform manual matching for unmatched items."""
        self.log("Starting manual matching process...")
        
        # Navigate back to account
        self.frame = self.wait_for_iframe()
        account_link = self.frame.get_by_role("link", name=self.account_name).last
        self.smart_click(account_link, f"account link '{self.account_name}'")
        self.page.wait_for_timeout(5000)
        
        # Process all pages with matching
        total_processed = self.process_pagination_with_matching()
        self.log(f"Manual matching complete - {total_processed} rows processed")
        
        # Process matched items
        self.log("Processing manually matched items...")
        process_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
            "#ctl00_phDS_ds_ToolBar_ProcessMatched"
        ).get_by_text("Process")
        self.smart_click(process_button, "Process button (after manual matching)")
        self.page.wait_for_timeout(5000)
        
        # Go back to list
        back_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
            "#ctl00_phDS_ds_ToolBar_CancelCloseToList div"
        ).nth(0)
        self.smart_click(back_button, "Back to list button")
        self.page.wait_for_timeout(3000)
    
    def download_results(self) -> str:
        """
        Download the processed results as Excel.
        Returns the path to the downloaded file.
        """
        self.log("Downloading results...")
        
        # Navigate to account one more time
        self.frame = self.wait_for_iframe()
        account_link = self.frame.get_by_role("link", name=self.account_name).last
        self.smart_click(account_link, f"account link '{self.account_name}'")
        self.page.wait_for_timeout(5000)
        
        # Open export dropdown
        dropdown_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
            "#ctl00_phG_PXSplitContainer_grid1_at_tlb_ul > li:nth-child(14)"
        )
        self.smart_click(dropdown_button, "Export dropdown")
        
        # Trigger download
        with self.page.expect_download() as download_info:
            download_button = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_at_tlb_menuhi_item_3")
            self.smart_click(download_button, "Export to Excel button")
        
        # Save download
        download = download_info.value
        filename = download.suggested_filename
        self.log(f"Download started: {filename}")
        
        save_path = os.path.join(self.download_dir, filename)
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        
        download.save_as(save_path)
        self.log(f"âœ… File saved to: {save_path}")
        
        # Verify file exists
        if not os.path.exists(save_path):
            raise FileNotFoundError(f"Downloaded file not found at {save_path}")
        
        return save_path
    
    def process_downloaded_file(self, save_path: str) -> list:
        """
        Process the downloaded Excel file and return cleaned records.
        """
        self.log(f"Processing downloaded file: {save_path}")
        
        # Load Excel file
        df = safe_read_excel(save_path)
        
        # Clean data
        # Convert datetime columns
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%d/%m/%Y")
        
        # Replace infinities and NaNs
        df = df.replace([float("inf"), float("-inf")], None)
        df = df.fillna("")
        
        # Convert to string
        df = df.astype(str)
        
        # Preserve leading zeros in Bank Reference Number
        if "Bank Reference Number" in df.columns:
            df["Bank Reference Number"] = df["Bank Reference Number"].str.zfill(2)
        
        self.log(f"Processed {len(df)} records from downloaded file")
        
        return df.to_dict(orient="records")
    
    def run(self) -> list:
        """
        Main execution method - orchestrates the entire CA Match process.
        Returns list of processed records.
        """
        save_path = None
        
        try:
            self.send_pingback("started")
            self.log("=" * 60)
            self.log("CA MATCH PROCESS - OPTIMIZED VERSION")
            self.log("=" * 60)
            
            # Initialize browser
            self.initialize_browser()
            
            # Login
            self.log("Logging in...")
            login(self.page, self.website_url, self.username, self.password)
            
            # Navigate to Process Bank Records
            self.log("Navigating to Process Bank Records...")
            navigatePage(self.page, "Process Bank Records")
            
            # Perform auto-match
            self.perform_auto_match()
            
            # Perform manual matching
            self.perform_manual_matching()
            
            # Download results
            save_path = self.download_results()
            
            # Process downloaded file
            records = self.process_downloaded_file(save_path)
            
            # Cleanup browser
            self.cleanup()
            
            # Send success notification
            self.send_pingback("completed")
            
            # Send email notification (if configured)
            try:
                reply_to_trigger_email("âœ… CAMatch process completed successfully.")
            except Exception as e:
                self.log(f"Email notification failed: {e}", "warning")
            
            # Chain to next process
            self.log("Chaining to Extract Reconciliation Statement...")
            ExtractReconcileStatement.extract_reconciliation_statements(
                playwright=self.playwright,
                accountName=self.account_name,
                date=self.date,
                amount=self.amount,
                save_path=save_path,
                website_url=self.website_url,
                username=self.username,
                password=self.password,
                pingback_url=self.pingback_url,
                payload=self.payload,
                webhook_url=self.webhook_url,
                headless=self.headless
            )
            
            self.log("=" * 60)
            self.log("CA MATCH PROCESS COMPLETED SUCCESSFULLY")
            self.log("=" * 60)
            
            return records
            
        except Exception as e:
            self.log(f"FATAL ERROR: {e}", "error")
            self.send_pingback("failed", str(e))
            
            # Send failure email
            try:
                reply_to_trigger_email(f"âŒ CAMatch process failed: {str(e)}")
            except:
                pass
            
            # Cleanup on error
            self.cleanup()
            
            raise


# Convenience function for backward compatibility
def process_bank_transactions(
    playwright: Playwright,
    accountName: str,
    date: str,
    amount: float,
    website_url: str = None,
    username: str = None,
    password: str = None,
    pingback_url: str = None,
    payload: dict = None,
    webhook_url: str = None,
    headless: bool = False
) -> list:
    """
    Process bank transactions with CA Match automation.
    
    Args:
        playwright: Playwright instance
        accountName: Name of the cash account to process
        date: Date for reconciliation (format: DD/MM/YYYY)
        amount: Statement balance amount
        website_url: Website URL (defaults to env var)
        username: Login username (defaults to env var)
        password: Login password (defaults to env var)
        pingback_url: Optional URL for status callbacks
        payload: Optional payload for pingback
        webhook_url: Optional URL for logging webhooks
        headless: Run browser in headless mode (default: False)
    
    Returns:
        List of processed transaction records
    """
    processor = CAMatchProcessor(
        playwright=playwright,
        account_name=accountName,
        date=date,
        amount=amount,
        website_url=website_url,
        username=username,
        password=password,
        pingback_url=pingback_url,
        payload=payload,
        webhook_url=webhook_url,
        headless=headless
    )
    
    return processor.run()


# Main execution
if __name__ == "__main__":
    # Calculate date (one month ago)
    today = datetime.today()
    one_month_ago = today - relativedelta(months=1)
    formatted_date = one_month_ago.strftime("%d/%m/%Y")
    
    # Run process
    with sync_playwright() as playwright:
        records = process_bank_transactions(
            playwright=playwright,
            accountName=os.getenv("accountName"),
            date=formatted_date,
            amount=100.00,
            website_url=os.getenv("WEBSITE_URL"),
            username=os.getenv("WEBSITE_USERNAME"),
            password=os.getenv("PASSWORD"),
            pingback_url=None,
            payload=None,
            webhook_url=None,
            headless=False
        )
        
        print(f"\nâœ… Process completed successfully!")
        print(f"ðŸ“Š Processed {len(records)} records")
