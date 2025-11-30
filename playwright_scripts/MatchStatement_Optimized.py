"""
Match Statement - Optimized Version
===================================
This module handles the automated matching of bank statements with company records
with improved robustness, error handling, and efficiency.

Key Improvements:
- Intelligent waiting strategies
- Better error handling with retry logic
- Cleaner separation of concerns
- Enhanced logging with clear step labeling
- Improved table detection and filtering
"""

import os
from typing import Dict, List, Any

import pandas as pd
import requests
from dotenv import load_dotenv
from playwright.sync_api import Playwright, expect, sync_playwright

from helper_playwright import functions
from helper_playwright.email_reply import reply_to_trigger_email, reply_with_attachment

# Load environment variables
load_dotenv()


class MatchStatementProcessor:
    """Handles statement matching automation with improved robustness."""
    
    def __init__(
        self,
        playwright: Playwright,
        match_result_path: str,
        account_name: str,
        website_url: str = None,
        username: str = None,
        password: str = None,
        pingback_url: str = None,
        payload: dict = None,
        webhook_url: str = None,
        headless: bool = False
    ):
        self.playwright = playwright
        self.match_result_path = match_result_path
        self.account_name = account_name
        self.website_url = website_url or os.getenv("WEBSITE_URL")
        self.username = username or os.getenv("WEBSITE_USERNAME")
        self.password = password or os.getenv("PASSWORD")
        self.pingback_url = pingback_url
        self.payload = payload
        self.webhook_url = webhook_url
        self.headless = headless
        
        self.browser = None
        self.page = None
        self.frame = None
        self.failed_entries: List[Dict[str, Any]] = []
        
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
                requests.post(self.pingback_url, json=data, timeout=10)
            except Exception as e:
                self.log(f"Pingback failed: {e}", "warning")
    
    def initialize_browser(self):
        """STEP 1: Initialize browser."""
        self.log("=" * 60)
        self.log("STEP 1: Initializing browser...")
        self.log("=" * 60)
        
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        self.page = self.browser.new_page()
        self.log("✅ Browser initialized successfully")
    
    def cleanup(self):
        """Clean up browser resources."""
        try:
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
            return True
        except:
            try:
                locator.click(force=True, timeout=5000)
                return True
            except:
                try:
                    locator.evaluate("el => el.click()")
                    return True
                except Exception as e:
                    self.log(f"All click strategies failed for {description}: {e}", "error")
                    return False
    
    def is_table_empty(self, rows) -> bool:
        """Check if table has any meaningful data."""
        row_count = rows.count()
        for i in range(row_count):
            row_text = rows.nth(i).inner_text().strip()
            if row_text and row_text not in ["0.00\n0.00", "No records found", ""]:
                return False
        return True
    
    def filter_table(self, header_text: str, textbox_selector: str, value: str):
        """Filter table by clicking header and entering value."""
        try:
            header = self.frame.locator("td.GridHeader.GridRow", has_text=header_text).first
            textbox = self.frame.locator(textbox_selector)
            
            # Click header
            self.smart_click(header, f"{header_text} header")
            self.page.wait_for_timeout(500)
            
            # Wait for textbox
            try:
                textbox.wait_for(state="visible", timeout=5000)
            except:
                self.log(f"Textbox for '{header_text}' not visible, retrying...", "warning")
                self.smart_click(header, f"{header_text} header (retry)")
                self.page.wait_for_timeout(1000)
                textbox.wait_for(state="visible", timeout=5000)
            
            if not textbox.is_visible():
                self.log(f"Textbox for '{header_text}' still hidden, skipping", "warning")
                return
            
            # Fill and apply filter
            equals_button = self.frame.get_by_text("Equals", exact=True).first
            self.smart_click(equals_button, "Equals button")
            self.smart_click(textbox, f"{header_text} textbox")
            textbox.fill(str(value))
            
            ok_button = self.frame.get_by_role("button", name="OK")
            self.smart_click(ok_button, "OK button")
            self.page.wait_for_timeout(2000)
            
            self.log(f"✅ Filtered '{header_text}' with value '{value}'")
            
        except Exception as e:
            self.log(f"Filter failed for '{header_text}': {e}", "error")
    
    def ensure_match_to_payments_tab_selected(self):
        """Ensure the 'Match to Payments' tab is selected."""
        try:
            # Try to find the tab by text
            tab = self.frame.get_by_text("MATCH TO PAYMENTS", exact=True)
            if tab.count() == 0:
                 # Fallback to partial match or specific ID if known (based on previous logs/code structure)
                 # The ID often looks like #ctl00_phG_PXSplitContainer_tab2_tab0
                 tab = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_tab0")
            
            if tab.count() > 0:
                # Check if it looks selected (optional, but clicking it is usually safe)
                self.log("Ensuring 'Match to Payments' tab is selected")
                self.smart_click(tab, "Match to Payments tab")
                self.page.wait_for_timeout(1000)
                return True
            else:
                self.log("Could not find 'Match to Payments' tab", "warning")
                return False
        except Exception as e:
            self.log(f"Error selecting 'Match to Payments' tab: {e}", "warning")
            return False

    def search_and_match_csgp_ref(self, csgp_ref: str) -> bool:
        """Search for CSGP reference and click match if found."""
        try:
            # Get textbox
            textbox = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text")
            
            # Wait for textbox
            try:
                textbox.wait_for(state="visible", timeout=5000)
            except Exception:
                self.log(f"Textbox not visible for {csgp_ref}, trying to select tab...", "warning")
                # Retry by selecting the tab first
                self.ensure_match_to_payments_tab_selected()
                try:
                    # Try refocusing iframe and retrying
                    self.page.frame_locator("iframe[name='main']").locator("body").click()
                    self.page.wait_for_timeout(800)
                    textbox = self.page.frame_locator("iframe[name='main']").locator(
                        "#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text"
                    )
                    textbox.wait_for(state="visible", timeout=10000)
                except Exception as e2:
                    self.log(f"Textbox still not visible after retry: {e2}", "error")
                    return False
            
            # Fill textbox
            try:
                textbox.click(force=True)
                textbox.fill(str(csgp_ref))
                self.page.wait_for_timeout(1500)
            except Exception as e:
                self.log(f"Failed to fill textbox for {csgp_ref}: {e}", "error")
                return False
            
            # Click search
            search_button = self.frame.locator(
                "#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb > div.buttonsCont > div > div"
            )
            search_button.hover()
            self.smart_click(search_button, "Search button")
            
            # Detect table type
            table_a = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
            table_b = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")
            
            detail_table = None
            table_type = None
            
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
                    self.log(f"No detail table found for {csgp_ref}", "warning")
                    return False
            
            # Check for "Nothing found"
            if detail_table.locator("td:has-text('Nothing has been found')").count() > 0:
                self.log(f"No matches found for {csgp_ref}", "warning")
                return False
            
            # Check if table is empty
            rows = detail_table.locator("tr")
            if self.is_table_empty(rows):
                self.log(f"Table empty for {csgp_ref}", "warning")
                return False
            
            # Get data rows
            data_rows = detail_table.locator("tbody tr")
            row_count = data_rows.count()
            self.log(f"Found {row_count} rows in detail table (Type {table_type})")
            
            if row_count < 2:
                self.log(f"Not enough rows for {csgp_ref}", "warning")
                return False
            
            # Click second column of first data row
            target_row = data_rows.nth(0)
            second_col = target_row.locator("td").nth(1)
            
            if second_col.count() == 0:
                self.log(f"Second column not found for {csgp_ref}", "warning")
                return False
            
            self.log(f"✅ Clicking match for {csgp_ref}")
            self.smart_click(second_col, f"Match checkbox for {csgp_ref}")
            self.page.wait_for_timeout(1000)
            
            return True
            
        except Exception as e:
            self.log(f"Error matching {csgp_ref}: {e}", "error")
            return False
    
    def process_1to1_matches(self, df: pd.DataFrame):
        """STEP 5: Process 1-to-1 matches."""
        self.log("=" * 60)
        self.log(f"STEP 5: Processing 1-to-1 Matches ({len(df)} rows)")
        self.log("=" * 60)
        
        # Ensure correct tab is selected
        self.ensure_match_to_payments_tab_selected()
        
        for index, row in df.iterrows():
            bank_ref_raw = row.get("Bank Reference Number")
            csgp_ref_raw = row.get("CSGP Reference")
            
            # Skip empty rows
            if pd.isna(bank_ref_raw) or pd.isna(csgp_ref_raw):
                continue
            if str(bank_ref_raw).strip() == "" or str(csgp_ref_raw).strip() == "":
                continue
            
            # Clean references
            bank_ref = self.clean_ref(bank_ref_raw)
            csgp_ref = self.clean_ref(csgp_ref_raw)
            
            self.log(f"[1to1] Row {index+1}: BankRef={bank_ref}, CSGPRef={csgp_ref}")
            
            # Filter main table by bank reference
            self.filter_table("Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", bank_ref)
            
            # Check if table has results
            table = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
            rows = table.locator("tbody tr")
            
            if self.is_table_empty(rows):
                self.log(f"No records found for BankRef={bank_ref}", "warning")
                self.failed_entries.append(row.to_dict())
                continue
            
            # Check first row for warning icon
            if rows.count() > 0:
                first_row = rows.nth(0)
                first_col = first_row.locator("td").nth(0)
                warning_icon = first_col.locator("div")
                
                if warning_icon.count() > 0:
                    self.log(f"Warning icon present for {bank_ref}, skipping", "warning")
                    self.failed_entries.append(row.to_dict())
                    continue
                else:
                    # Proceed with matching
                    self.search_and_match_csgp_ref(csgp_ref)
        
        self.log(f"✅ Completed 1-to-1 matches")
    
    def enable_multiple_matching(self):
        """Enable multiple matching checkbox if available."""
        try:
            # Try Type A
            checkbox_a = self.frame.locator(
                "#ctl00_phG_PXSplitContainer_tab2_t1_frmCreateDocumentInv_edMultipleMatching_text"
            )
            if checkbox_a.count() > 0 and not checkbox_a.first.is_checked():
                self.log("Enabling Multiple Matching (Type A)")
                self.smart_click(checkbox_a.first, "Multiple Matching checkbox (Type A)")
                return
        except:
            pass
        
        try:
            # Try Type B
            checkbox_b = self.frame.locator(
                "#ctl00_phG_PXSplitContainer_tab2_t0_frmMatchToPayments_edMultipleMatchingToPayments_text"
            )
            if checkbox_b.count() > 0 and not checkbox_b.first.is_checked():
                self.log("Enabling Multiple Matching (Type B)")
                self.smart_click(checkbox_b.first, "Multiple Matching checkbox (Type B)")
                return
        except:
            pass
        
        self.log("No Multiple Matching checkbox found", "warning")
    
    def clean_ref(self, ref: str) -> str:
        """Clean reference number."""
        try:
            return str(int(float(ref)))
        except:
            return str(ref).strip()
    
    def process_group_matches(self, df: pd.DataFrame):
        """STEP 6: Process group matches (1-to-many)."""
        self.log("=" * 60)
        self.log(f"STEP 6: Processing Group Matches ({len(df)} rows)")
        self.log("=" * 60)
        
        # Ensure correct tab is selected
        self.ensure_match_to_payments_tab_selected()
        
        for index, row in df.iterrows():
            bank_ref_raw = str(row.get("Bank Reference Number", "")).strip()
            csgp_ref_raw = str(row.get("CSGP Reference", "")).strip()
            
            if not bank_ref_raw or not csgp_ref_raw:
                continue
            
            # Take first bank ref
            bank_ref = bank_ref_raw.split(",")[0].strip()
            
            # Split CSGP refs
            csgp_refs = [self.clean_ref(ref) for ref in csgp_ref_raw.split(",") if ref.strip()]
            
            self.log(f"[Group] Row {index+1}: BankRef={bank_ref}, CSGPRefs={csgp_refs}")
            
            # Filter by bank reference
            self.filter_table("Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", bank_ref)
            
            # Check table
            table = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
            rows = table.locator("tbody tr")
            
            if self.is_table_empty(rows):
                self.log(f"No records for BankRef={bank_ref}", "warning")
                self.failed_entries.append(row.to_dict())
                continue
            
            # Enable multiple matching
            self.enable_multiple_matching()
            self.page.wait_for_timeout(1000)
            
            # Match each CSGP ref
            for csgp_ref in csgp_refs:
                self.log(f"[Group] Matching CSGPRef={csgp_ref}")
                self.search_and_match_csgp_ref(csgp_ref)
        
        self.log(f"✅ Completed group matches")
    
    def save_failed_entries(self):
        """Save failed entries to Excel file."""
        columns = [
            "Bank Statement Date", "Bank Transaction ID", "Bank Reference Number", "Bank Description",
            "Bank Receipt", "Bank Disbursement",
            "CSGP Transaction Date", "CSGP Reference", "CSGP Module", "CSGP Description",
            "CSGP Receipt", "CSGP Disbursement",
            "Amount Difference", "Date Difference", "Reason", "Confidence", "Match Type",
            "Bank_UID", "CSGP_UID"
        ]
        
        if self.failed_entries:
            df = pd.DataFrame(self.failed_entries)
            
            # Ensure all columns exist
            for col in columns:
                if col not in df.columns:
                    df[col] = ""
            
            df = df[columns]
            df.to_excel("failed_entries.xlsx", index=False)
            self.log(f"❌ Saved {len(self.failed_entries)} failed entries to failed_entries.xlsx")
        else:
            self.log("✅ No failed entries")
    
    def run(self):
        """
        Main execution method - orchestrates the entire matching process.
        """
        try:
            self.send_pingback("started")
            self.log("=" * 60)
            self.log("MATCH STATEMENT PROCESS - OPTIMIZED VERSION")
            self.log("=" * 60)
            
            # STEP 1: Initialize browser
            self.initialize_browser()
            
            # STEP 2: Login
            self.log("=" * 60)
            self.log("STEP 2: Logging in...")
            self.log("=" * 60)
            functions.login(self.page, self.website_url, self.username, self.password)
            self.log("✅ Login successful")
            
            # STEP 3: Navigate to Process Bank Records
            self.log("=" * 60)
            self.log("STEP 3: Navigating to Process Bank Records")
            self.log("=" * 60)
            functions.navigatePage(self.page, "Process Bank Records")
            
            self.frame = self.wait_for_iframe()
            account_link = self.frame.get_by_role("link", name=self.account_name).last
            self.smart_click(account_link, f"Account link: {self.account_name}")
            self.page.wait_for_timeout(5000)
            self.log("✅ Navigation successful")
            
            # STEP 4: Load match results
            self.log("=" * 60)
            self.log(f"STEP 4: Loading match results from {self.match_result_path}")
            self.log("=" * 60)
            dfs = pd.read_excel(
                self.match_result_path,
                sheet_name=["1to1 Matches", "Group Match"],
                dtype=str
            )
            self.log(f"✅ Loaded {sum(len(df) for df in dfs.values())} total rows")
            
            # STEP 5: Process 1-to-1 matches
            if "1to1 Matches" in dfs:
                self.process_1to1_matches(dfs["1to1 Matches"])
            
            # STEP 6: Process group matches
            if "Group Match" in dfs:
                self.process_group_matches(dfs["Group Match"])
            
            # STEP 7: Process matched items
            self.log("=" * 60)
            self.log("STEP 7: Processing matched items")
            self.log("=" * 60)
            process_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
                "#ctl00_phDS_ds_ToolBar_ProcessMatched"
            ).get_by_text("Process")
            self.smart_click(process_button, "Process button")
            self.page.wait_for_timeout(5000)
            self.log("✅ Matched items processed")
            
            # STEP 8: Save failed entries
            self.log("=" * 60)
            self.log("STEP 8: Saving failed entries")
            self.log("=" * 60)
            self.save_failed_entries()
            
            # Cleanup
            self.cleanup()
            
            # Send success notification
            self.send_pingback("completed")
            
            # Send email with attachment
            try:
                reply_with_attachment(
                    reply_text="✅ Match Statement process completed successfully. Please find the attached file.",
                    attachment_path="failed_entries.xlsx"
                )
            except Exception as e:
                self.log(f"Email notification failed: {e}", "warning")
            
            self.log("=" * 60)
            self.log("MATCH STATEMENT PROCESS COMPLETED SUCCESSFULLY")
            self.log("=" * 60)
            
        except Exception as e:
            self.log(f"FATAL ERROR: {e}", "error")
            self.send_pingback("failed", str(e))
            
            # Send failure email
            try:
                reply_to_trigger_email(f"❌ Match Statement failed: {str(e)}")
            except:
                pass
            
            # Cleanup on error
            self.cleanup()
            
            raise


# Convenience function for backward compatibility
def run_matching_process(
    playwright: Playwright,
    matchresultpath: str,
    website_url: str = None,
    username: str = None,
    password: str = None,
    accountName: str = None,
    pingback_url: str = None,
    payload: dict = None,
    webhook_url: str = None,
    headless: bool = False
):
    """
    Run the matching process with automation.
    
    Args:
        playwright: Playwright instance
        matchresultpath: Path to the Excel file with match results
        website_url: Website URL (defaults to env var)
        username: Login username (defaults to env var)
        password: Login password (defaults to env var)
        accountName: Account name (defaults to env var)
        pingback_url: Optional URL for status callbacks
        payload: Optional payload for pingback
        webhook_url: Optional URL for logging webhooks
        headless: Run browser in headless mode (default: False)
    """
    processor = MatchStatementProcessor(
        playwright=playwright,
        match_result_path=matchresultpath,
        account_name=accountName or os.getenv("accountName"),
        website_url=website_url,
        username=username,
        password=password,
        pingback_url=pingback_url,
        payload=payload,
        webhook_url=webhook_url,
        headless=headless
    )
    
    processor.run()


# Main execution
if __name__ == "__main__":
    import config
    with sync_playwright() as playwright:
        run_matching_process(
            playwright,
            website_url=os.getenv("WEBSITE_URL"),
            username=os.getenv("WEBSITE_USERNAME"),
            password=os.getenv("PASSWORD"),
            accountName=os.getenv("accountName"),
            matchresultpath="matching_results/MATCHLIST_MBB02_20251024_160020.xlsx",
            pingback_url=None,
            payload=None,
            webhook_url=None
        )
