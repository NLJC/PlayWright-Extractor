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
import re
from typing import Dict, List, Any, Set
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv
from playwright.sync_api import Playwright, expect, sync_playwright

from helper_playwright.functions import (
    login, navigatePage, wait_for_iframe, smart_click, 
    is_table_empty, smart_wait_for_page_load, filter_table,
    safe_read_excel
)
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
        headless: bool = False,
        target_date: str = None
    ):
        self.playwright = playwright
        self.match_result_path = match_result_path
        self.account_name = account_name
        self.target_date = target_date
        self.website_url = website_url or os.getenv("WEBSITE_URL")
        self.username = username or os.getenv("WEBSITE_USERNAME")
        self.password = password or os.getenv("PASSWORD")
        self.pingback_url = pingback_url
        self.payload = payload
        self.webhook_url = webhook_url
        self.headless = headless
        
        self.browser = None
        self.context = None  # Add context for video recording
        self.page = None
        self.frame = None
        self.failed_entries: List[Dict[str, Any]] = []
        self.failed_bank_refs: Set[str] = set()  # Track failed BankRefs to prevent duplicates
        self.processed_bank_refs: Set[str] = set()  # Track successfully processed BankRefs to prevent duplicates

        # Load page wait time from environment variable (default: 15000ms = 15 seconds)
        self.page_wait_time = int(os.getenv("PAGE_WAIT_TIME_MS", "15000"))

        # Load debug mode from environment variable
        self.debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"

        # Setup centralized logging to logs/runs/ directory
        self.log_file = None
        self._setup_log_file()

    def _setup_log_file(self):
        """Setup log file in logs/runs/ directory."""
        try:
            # Check for SAVE_DIRECTORY env var (from inbox_listener)
            save_dir = os.getenv("SAVE_DIRECTORY")
            
            if save_dir:
                # Use the run-specific folder
                log_dir = Path(save_dir) / "logs"
                print(f"[INFO] Using run-specific log directory: {log_dir}")
            else:
                # Fallback to default logs/runs directory
                log_dir = Path("logs/runs")
            
            log_dir.mkdir(parents=True, exist_ok=True)

            # Create log file with timestamp and account name
            timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
            log_filename = f"playwright-match-{self.account_name}-{timestamp}-{os.getpid()}.log"
            self.log_file = log_dir / log_filename

            # Write header to log file
            with open(self.log_file, 'w', encoding='utf-8') as f:
                f.write(f"{'='*80}\n")
                f.write(f"Playwright Match Statement Process\n")
                f.write(f"Account: {self.account_name}\n")
                f.write(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write(f"Match Result Path: {self.match_result_path}\n")
                f.write(f"Debug Mode: {'ENABLED' if self.debug_mode else 'DISABLED'}\n")
                f.write(f"{'='*80}\n\n")

            print(f"[INFO] Logging to: {self.log_file}")
            if self.debug_mode:
                print(f"[INFO] Debug mode: ENABLED (detailed logs will be shown)")
            else:
                print(f"[INFO] Debug mode: DISABLED (set DEBUG_MODE=true in .env to enable)")
        except Exception as e:
            print(f"[WARNING] Could not setup log file: {e}")
            self.log_file = None

    def log(self, message: str, level: str = "info"):
        """Centralized logging with file and webhook support."""
        # Skip debug messages if debug mode is disabled
        if level == "debug" and not self.debug_mode:
            return

        log_message = f"[{level.upper()}] {message}"
        print(log_message)

        # Write to log file
        if self.log_file:
            try:
                with open(self.log_file, 'a', encoding='utf-8') as f:
                    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    f.write(f"{timestamp} | {log_message}\n")
            except Exception as e:
                print(f"[WARNING] Could not write to log file: {e}")

        # Send to webhook if configured
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
                viewport={"width": 1280, "height": 720}
            )
        else:
            self.context = self.browser.new_context(
                 viewport={"width": 1280, "height": 720}
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
                        new_path = os.path.join(folder, f"match_statement_{timestamp}.webm")
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
            locator.click(timeout=int(self.page_wait_time))
            return True
        except:
            try:
                locator.click(force=True, timeout=int(self.page_wait_time))
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

    def smart_wait_for_page_load(self, additional_check=None):
        """
        Smart wait that proceeds as soon as page is ready instead of waiting full duration.
        Uses network idle detection and optional additional checks.

        Args:
            additional_check: Optional lambda function that returns True when ready
        """
        try:
            # Wait for network to be idle (no more than 2 network connections for 500ms)
            self.page.wait_for_load_state("networkidle", timeout=self.page_wait_time)

            # If additional check provided, wait for it with polling
            if additional_check:
                start_time = self.page.evaluate("Date.now()")
                while True:
                    if additional_check():
                        break
                    current_time = self.page.evaluate("Date.now()")
                    if current_time - start_time > self.page_wait_time:
                        break
                    self.page.wait_for_timeout(200)  # Poll every 200ms

            # Small buffer to ensure stability
            self.page.wait_for_timeout(500)

        except Exception as e:
            # If smart wait fails, fall back to simple timeout
            self.log(f"Smart wait failed, using fallback: {e}", "debug")
            self.page.wait_for_timeout(self.page_wait_time)
    
    def filter_table(self, header_text: str, textbox_selector: str, value: str):
        """Filter table by clicking header and entering value."""
        try:
            header = self.frame.locator("td.GridHeader.GridRow", has_text=header_text).first
            textbox = self.frame.locator(textbox_selector)
            
            # Click header
            smart_click(self.page, header, f"{header_text} header")
            self.page.wait_for_timeout(500)
            
            # Wait for textbox
            try:
                textbox.wait_for(state="visible", timeout=int(self.page_wait_time))
            except:
                self.log(f"Textbox for '{header_text}' not visible, retrying...", "warning")
                smart_click(self.page, header, f"{header_text} header (retry)")
                self.page.wait_for_timeout(1000)
                textbox.wait_for(state="visible", timeout=int(self.page_wait_time))
            
            if not textbox.is_visible():
                self.log(f"Textbox for '{header_text}' still hidden, skipping", "warning")
                return
            
            # Fill and apply filter
            # Fill and apply filter - Use Contains instead of Equals for robustness
            contains_button = self.frame.get_by_text("Contains", exact=True).first
            if contains_button.count() > 0:
                smart_click(self.page, contains_button, "Contains button")
            else:
                 # If Contains not found, try default (often default is fine) or fall back to Equals
                 self.log("'Contains' option not found, trying default or Equals...", "debug")
                 pass
            smart_click(self.page, textbox, f"{header_text} textbox")
            textbox.fill(str(value))
            
            ok_button = self.frame.get_by_role("button", name="OK").first
            smart_click(self.page, ok_button, "OK button")

            # Smart wait for filter to apply
            smart_wait_for_page_load(self.page)

            self.log(f"[OK] Filtered '{header_text}' with value '{value}'")
            
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
                smart_click(self.page, tab, "Match to Payments tab")
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
                textbox.wait_for(state="visible", timeout=int(self.page_wait_time))
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
            smart_click(self.page, search_button, "Search button")
            
            # Detect table type
            table_a = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
            table_b = self.frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")
            
            detail_table = None
            table_type = None
            
            try:
                table_a.wait_for(state="visible", timeout=int(self.page_wait_time))
                detail_table = table_a
                table_type = "A"
            except:
                try:
                    table_b.wait_for(state="visible", timeout=int(self.page_wait_time))
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
            
            self.log(f"[OK] Clicking match for {csgp_ref}")
            smart_click(self.page, second_col, f"Match checkbox for {csgp_ref}")
            self.page.wait_for_timeout(1000)
            
            return True
            
        except Exception as e:
            self.log(f"Error matching {csgp_ref}: {e}", "error")
            return False
    
    def process_1to1_matches(self, df: pd.DataFrame):
        """STEP 6: Process 1-to-1 matches."""
        self.log("=" * 60)
        self.log(f"STEP 6: Processing 1-to-1 Matches ({len(df)} rows)")
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
            
            # Skip if already processed
            if bank_ref in self.processed_bank_refs:
                self.log(f"[1to1] Skipping BankRef={bank_ref} (already processed in previous step)")
                continue

            self.log(f"[1to1] Row {index+1}: BankRef={bank_ref}, CSGPRef={csgp_ref}")
            
            # Filter main table by bank reference
            self.filter_table("Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", bank_ref)
            
            # Check if table has results
            table = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
            rows = table.locator("tbody tr")
            
            if self.is_table_empty(rows):
                self.log(f"No records found for BankRef={bank_ref}", "warning")
                if bank_ref not in self.failed_bank_refs:
                    self.failed_entries.append(row.to_dict())
                    self.failed_bank_refs.add(bank_ref)
                continue
            
            # Check first row for warning icon
            if rows.count() > 0:
                first_row = rows.nth(0)
                first_col = first_row.locator("td").nth(0)
                warning_icon = first_col.locator("div")
                
                if warning_icon.count() > 0:
                    self.log(f"Warning icon present for {bank_ref}, skipping", "warning")
                    if bank_ref not in self.failed_bank_refs:
                        self.failed_entries.append(row.to_dict())
                        self.failed_bank_refs.add(bank_ref)
                    continue
                else:
                    self.search_and_match_csgp_ref(csgp_ref)
                    # Mark as processed
                    self.processed_bank_refs.add(bank_ref)
        
        self.log(f"[OK] Completed 1-to-1 matches")
    
    def enable_multiple_matching(self):
        """Enable multiple matching checkbox if available."""
        self.log("Checking 'Match to Multiple Payments' checkbox...")

        # Strategy 1: Try Type A ID (Original Method)
        try:
            checkbox_a = self.frame.locator(
                "#ctl00_phG_PXSplitContainer_tab2_t1_frmCreateDocumentInv_edMultipleMatching_text"
            )
            if checkbox_a.count() > 0:
                if not checkbox_a.first.is_checked():
                    self.log("Enabling Multiple Matching (Type A)")
                    smart_click(self.page, checkbox_a.first, "Multiple Matching checkbox (Type A)")
                else:
                    self.log("'Match to Multiple Payments' (Type A) is already checked")
                return
        except:
            pass
        
        # Strategy 2: Try Type B ID (Original Method)
        try:
            checkbox_b = self.frame.locator(
                "#ctl00_phG_PXSplitContainer_tab2_t0_frmMatchToPayments_edMultipleMatchingToPayments_text"
            )
            if checkbox_b.count() > 0:
                if not checkbox_b.first.is_checked():
                     self.log("Enabling Multiple Matching (Type B)")
                     smart_click(self.page, checkbox_b.first, "Multiple Matching checkbox (Type B)")
                else:
                    self.log("'Match to Multiple Payments' (Type B) is already checked")
                return
        except:
            pass

        # Strategy 3: Find by text label (Fallback / Robust Method)
        self.log("Original ID selectors failed, trying robust Label Search...")
        try:
            # Acumatica often puts the label next to the checkbox or inside a wrapper
            label = self.frame.get_by_text("Match to Multiple Payments", exact=True).first
            
            if label.count() > 0:
                self.log("Found 'Match to Multiple Payments' label")
                
                # Check if we can find the checkbox input itself
                # It might be a sibling or inside the same parent
                # Trying to find a checkbox input near this label
                checkbox = None
                
                # Check parent's input
                parent = label.locator("xpath=..")
                if parent.locator("input[type='checkbox']").count() > 0:
                    checkbox = parent.locator("input[type='checkbox']").first
                
                # Check preceding sibling
                elif self.frame.locator("input[type='checkbox']").filter(has=self.frame.locator("xpath=following-sibling::*[text()='Match to Multiple Payments']")).count() > 0:
                    checkbox = self.frame.locator("input[type='checkbox']").filter(has=self.frame.locator("xpath=following-sibling::*[text()='Match to Multiple Payments']")).first

                if checkbox and checkbox.count() > 0:
                    if not checkbox.is_checked():
                        self.log("Clicking 'Match to Multiple Payments' checkbox (via Label Strategy)")
                        smart_click(self.page, checkbox, "Match to Multiple Payments checkbox")
                        self.page.wait_for_timeout(1000)
                    else:
                        self.log("'Match to Multiple Payments' is already checked")
                    return
                else:
                    # If we found label but not input, try simple click on label (often toggles it)
                    # Use a heuristic: check if there's a checked state we can detect? 
                    # For now just click if we can't verify state, OR rely on fallback.
                    self.log("Could not pinpoint input from label, skipping fallback click to be safe.")
            
        except Exception as e:
            self.log(f"Strategy 3 (Label Search) failed: {e}", "debug")
        
        self.log("No Multiple Matching checkbox found", "warning")
    
    def clean_ref(self, ref: str) -> str:
        """Clean reference number."""
        try:
            return str(int(float(ref)))
        except:
            return str(ref).strip()
    
    def process_group_matches(self, df: pd.DataFrame):
        """STEP 7: Process group matches (1-to-many)."""
        self.log("=" * 60)
        self.log(f"STEP 7: Processing Group Matches ({len(df)} rows)")
        self.log("=" * 60)

        # Ensure correct tab is selected
        self.ensure_match_to_payments_tab_selected()

        for index, row in df.iterrows():
            bank_ref_raw = str(row.get("Bank Reference Number", "")).strip()
            csgp_ref_raw = str(row.get("CSGP Reference", "")).strip()
            match_type = str(row.get("Match Type", "")).strip().lower()

            if not bank_ref_raw or not csgp_ref_raw:
                continue

            # Skip if already processed (Check THIS first to avoid reverse_ce_gl confusion)
            if bank_ref_raw:
                first_bank_ref = bank_ref_raw.split(",")[0].strip()
                if first_bank_ref in self.processed_bank_refs:
                    self.log(f"[Group] Skipping BankRef={first_bank_ref} (already processed)")
                    continue



            # Skip reverse_ce_gl entries - they will be processed separately
            if match_type == "reverse_ce_gl":
                self.log(f"[Group] Row {index+1}: Skipping reverse_ce_gl entry (will be processed in Step 6.5)")
                continue

            # Take first bank ref
            bank_ref = bank_ref_raw.split(",")[0].strip()

            # Split CSGP refs
            csgp_refs = [self.clean_ref(ref) for ref in csgp_ref_raw.split(",") if ref.strip()]

            self.log(f"[Group] Row {index+1}: BankRef={bank_ref}, CSGPRefs={csgp_refs}, MatchType={match_type}")

            # Filter by bank reference
            self.filter_table("Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", bank_ref)

            # Check table
            table = self.frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
            rows = table.locator("tbody tr")

            if self.is_table_empty(rows):
                self.log(f"No records for BankRef={bank_ref}", "warning")
                if bank_ref not in self.failed_bank_refs:
                    self.failed_entries.append(row.to_dict())
                    self.failed_bank_refs.add(bank_ref)
                continue

            # Skip if already processed
            if bank_ref in self.processed_bank_refs:
                self.log(f"[Group] Skipping BankRef={bank_ref} (already processed)")
                continue

            # Take first bank ref

            # Enable multiple matching
            self.enable_multiple_matching()
            self.page.wait_for_timeout(1000)

            # Match each CSGP ref
            for csgp_ref in csgp_refs:
                self.log(f"[Group] Matching CSGPRef={csgp_ref}")
                self.search_and_match_csgp_ref(csgp_ref)

        self.log(f"[OK] Completed group matches")

    def process_reverse_ce_gl_matches(self, df: pd.DataFrame):
        """STEP 4.5: Process reverse CE/GL matches in Acumatica (FIRST)."""
        self.log("=" * 60)
        self.log(f"STEP 4.5: Processing Reverse CE/GL Matches ({len(df)} rows)")
        self.log("=" * 60)

        # Filter for reverse_ce_gl matches only
        if "Match Type" not in df.columns:
            self.log("'Match Type' column not found, skipping reverse_ce_gl processing")
            return

        reverse_ce_gl_df = df[df["Match Type"].str.lower() == "reverse_ce_gl"]

        if reverse_ce_gl_df.empty:
            self.log("No reverse_ce_gl matches found, skipping")
            return

        self.log(f"Found {len(reverse_ce_gl_df)} reverse_ce_gl matches to process")

        # Navigate to Reconciliation Statements ONCE at the beginning
        self.log("Navigating to Reconciliation Statements (one-time navigation)...")
        success = self.navigate_to_reconciliation_statements()
        if not success:
            self.log("Failed to navigate to Reconciliation Statements, skipping all reverse_ce_gl matches", "error")
            # Add all rows to failed entries
            for index, row in reverse_ce_gl_df.iterrows():
                self.failed_entries.append(row.to_dict())
            return

        # Process each reverse_ce_gl match WITHOUT navigating away
        for index, row in reverse_ce_gl_df.iterrows():
            csgp_ref_raw = str(row.get("CSGP Reference", "")).strip()

            if not csgp_ref_raw:
                continue

            # Split CSGP refs - reverse_ce_gl typically has 2 company transactions
            csgp_refs = [self.clean_ref(ref) for ref in csgp_ref_raw.split(",") if ref.strip()]

            if len(csgp_refs) != 2:
                self.log(f"[reverse_ce_gl] Row {index+1}: Expected 2 CSGP refs, got {len(csgp_refs)}. Skipping.", "warning")
                self.failed_entries.append(row.to_dict())
                continue

            self.log(f"[reverse_ce_gl] Row {index+1}: Processing CSGPRefs={csgp_refs}")

            # Search for the first CSGP reference in Document Ref column
            matching_records = self.search_document_ref_in_reconciliation(csgp_refs[0])

            if not matching_records:
                self.log(f"No records found for CSGP ref {csgp_refs[0]}", "warning")
                self.failed_entries.append(row.to_dict())
                continue

            # Validate and reconcile based on record count
            success = self.validate_and_reconcile_reverse_ce_gl(matching_records, csgp_refs)

            if not success:
                self.log(f"Failed to reconcile reverse_ce_gl for {csgp_refs}", "error")
                self.failed_entries.append(row.to_dict())
                continue

            self.log(f"[OK] Successfully processed reverse_ce_gl match for {csgp_refs}")
            
            # Track the bank reference if available in the row
            bank_ref_raw = str(row.get("Bank Reference Number", "")).strip()
            if bank_ref_raw:
                # Group matches might have comma-separated bank refs, usually it's one for reverse_ce_gl but handle split
                bank_refs = [self.clean_ref(ref) for ref in bank_ref_raw.split(",") if ref.strip()]
                for br in bank_refs:
                    self.processed_bank_refs.add(br)
                    self.log(f"[reverse_ce_gl] Marked BankRef={br} as processed")

        self.log(f"[OK] Completed all reverse_ce_gl matches")

    def navigate_to_reconciliation_statements(self) -> bool:
        """Navigate to CashBook -> Reconciliation Statements -> Account."""
        try:
            self.log("Navigating to CashBook...")

            # Click on CashBook in the menu (similar to navigatePage function)
            cashbook_link = self.page.locator("div").filter(has_text=re.compile(r"^Cash Book$")).first
            smart_click(self.page, cashbook_link, "CashBook menu")
            self.page.wait_for_timeout(1000)

            # Click on "Reconciliation Statements" button
            self.log("Clicking Reconciliation Statements button...")
            recon_button = self.page.get_by_role("link", name="Reconciliation Statements")
            recon_button.hover()
            self.page.wait_for_timeout(1000)
            smart_click(self.page, recon_button, "Reconciliation Statements button")

            # Smart wait for page to load instead of full timeout
            smart_wait_for_page_load(self.page)

            # Wait for iframe
            self.frame = self.wait_for_iframe()

            # Now select the account (e.g., CIM02) from the dropdown or link
            self.log(f"Selecting account: {self.account_name}")

            # Find all rows in the table to locate the correct account with "On Hold" status
            table = self.frame.locator("#ctl00_phG_grid_dataT0")

            try:
                table.wait_for(state="visible", timeout=int(self.page_wait_time))
                rows = table.locator("tbody tr")
                row_count = rows.count()

                target_row = None
                self.log(f"Found {row_count} rows in Reconciliation Statements table")

                # Strategy 1: Find valid rows with dates
                valid_rows = []

                for i in range(row_count):
                    row = rows.nth(i)
                    row_text = row.inner_text()
                    
                    # Ensure it's the correct account
                    if self.account_name not in row_text:
                        continue
                        
                    # Extract date from row (ColumnIndex 2 usually, based on typical grid)
                    # We'll try to find a date pattern in the text
                    # Example text: "CIM02 ... 08/01/2026 ... On Hold"
                    date_match = re.search(r"(\d{2}/\d{2}/\d{4})", row_text)
                    
                    row_date_str = date_match.group(1) if date_match else None
                    row_date_obj = None
                    
                    if row_date_str:
                        try:
                            row_date_obj = datetime.strptime(row_date_str, "%d/%m/%Y")
                        except:
                            pass
                    
                    valid_rows.append({
                        "row": row,
                        "date_str": row_date_str,
                        "date_obj": row_date_obj,
                        "text": row_text,
                        "index": i
                    })

                # Strategy 2: Select based on target_date
                if self.target_date:
                    self.log(f"Searching for account '{self.account_name}' with date '{self.target_date}'")
                    for item in valid_rows:
                        if item["date_str"] == self.target_date:
                            self.log(f"Found exact match for date {self.target_date} at row {item['index']}")
                            # Find the link
                            account_link = item["row"].get_by_role("link", name=self.account_name)
                            if account_link.count() > 0:
                                target_row = account_link.first
                                break
                
                # Strategy 3: Fallback to Latest Date
                if not target_row and valid_rows:
                    self.log(f"No exact match found for {self.target_date}, selecting latest available...")
                    # Sort by date descending
                    sorted_rows = sorted(
                        [r for r in valid_rows if r["date_obj"]], 
                        key=lambda x: x["date_obj"], 
                        reverse=True
                    )
                    
                    if sorted_rows:
                        latest = sorted_rows[0]
                        self.log(f"Selected latest record: {latest['date_str']} at row {latest['index']}")
                        account_link = latest["row"].get_by_role("link", name=self.account_name)
                        if account_link.count() > 0:
                            target_row = account_link.first
                
                # Strategy 4: Fallback to "On Hold" (Legacy/Original Logic) if still no target
                if not target_row:
                     self.log("Fallback to searching for 'On Hold' status...")
                     for i in range(row_count):
                        row = rows.nth(i)
                        row_text = row.inner_text()
                        if self.account_name in row_text and "On Hold" in row_text:
                            self.log(f"Found {self.account_name} with 'On Hold' status at row {i}")
                            account_link = row.get_by_role("link", name=self.account_name)
                            if account_link.count() > 0:
                                target_row = account_link.first
                                break

                if target_row:
                    smart_click(self.page, target_row, f"Account: {self.account_name}")
                    # Smart wait for account detail page to load
                    smart_wait_for_page_load(self.page)
                else:
                    # Fallback to first account link if no "On Hold" status found
                    self.log(f"No 'On Hold' {self.account_name} found, using first available", "warning")
                    account_link = self.frame.get_by_role("link", name=self.account_name).first
                    if account_link.count() > 0:
                        smart_click(self.page, account_link, f"Account: {self.account_name}")
                        # Smart wait for account detail page to load
                        smart_wait_for_page_load(self.page)
                    else:
                        self.log(f"Could not find account link for {self.account_name}", "warning")
                        return False

            except Exception as e:
                self.log(f"Error finding 'On Hold' account, trying fallback: {e}", "warning")
                # Fallback to original approach
                account_link = self.frame.get_by_role("link", name=self.account_name).first
                if account_link.count() > 0:
                    smart_click(self.page, account_link, f"Account: {self.account_name}")
                    # Smart wait for account detail page to load
                    smart_wait_for_page_load(self.page)
                else:
                    self.log(f"Could not find account link for {self.account_name}", "warning")
                    return False

            # After clicking account, we're now on the reconciliation detail page
            # The DETAILS tab should be automatically selected - verify the table is visible
            self.log("Verifying DETAILS tab is accessible...")
            # Smart wait for details tab to load
            smart_wait_for_page_load(self.page)

            # Try to find the details grid to confirm we're on the right view
            try:
                details_grid = self.frame.locator("#ctl00_phG_tab_t0_grid1")
                details_grid.wait_for(state="visible", timeout=int(self.page_wait_time))
                self.log("[OK] DETAILS tab is active and grid is visible")
            except:
                # Try clicking DETAILS tab explicitly
                self.log("DETAILS grid not visible, trying to click DETAILS tab...")
                try:
                    details_tab = self.frame.get_by_text("DETAILS", exact=True).first
                    if details_tab.count() > 0:
                        smart_click(self.page, details_tab, "DETAILS tab")
                        self.page.wait_for_timeout(self.page_wait_time)
                    else:
                        # Try by ID
                        tab_by_id = self.frame.locator("#ctl00_phG_tab_t0")
                        if tab_by_id.count() > 0:
                            smart_click(self.page, tab_by_id.first, "DETAILS tab (by ID)")
                            self.page.wait_for_timeout(self.page_wait_time)
                except Exception as e:
                    self.log(f"Could not explicitly click DETAILS tab: {e}", "warning")

            self.log("[OK] Successfully navigated to Reconciliation Statements")
            return True

        except Exception as e:
            self.log(f"Failed to navigate to Reconciliation Statements: {e}", "error")
            return False

    def search_document_ref_in_reconciliation(self, csgp_ref: str) -> List[Dict]:
        """Search for CSGP reference in Document Ref column and return matching records."""
        try:
            self.log(f"Searching for Document Ref: {csgp_ref}")

            # Smart wait for page to fully load
            smart_wait_for_page_load(self.page)

            # Use the correct table selector from the DETAILS tab
            table = None
            table_selectors = [
                "#ctl00_phG_tab_t0_grid1_dataT0",  # Correct selector from debug output
                "#ctl00_phG_tab_t0_grid_dataT0",
                "#ctl00_phG_grid_dataT0",
                "table[id*='grid'][id*='dataT0']",
            ]

            for selector in table_selectors:
                try:
                    test_table = self.frame.locator(selector)
                    test_table.wait_for(state="visible", timeout=int(self.page_wait_time))
                    table = test_table
                    self.log(f"Found table with selector: {selector}")
                    break
                except:
                    continue

            if not table:
                self.log("Could not find reconciliation table with any known selector", "warning")
                return []

            # Filter by "Document Ref." column (same approach as filter_table)
            filter_success = False

            try:
                # Find the "Document Ref." column header
                header = self.frame.locator("td.GridHeader.GridRow").filter(has_text="Document Ref.").first

                if header.count() == 0:
                    self.log("Could not find 'Document Ref.' column header", "warning")
                else:
                    self.log(f"Found 'Document Ref.' column header")

                    # Click the header to open filter dropdown
                    smart_click(self.page, header, "Document Ref. header")
                    self.page.wait_for_timeout(1000)

                    # Find the filter textbox
                    textbox_selector = "#ctl00_phG_tab_t0_grid1_fd_txt"
                    textbox = self.frame.locator(textbox_selector)
                    textbox.wait_for(state="visible", timeout=int(self.page_wait_time))

                    if textbox.is_visible():
                        # "Contains" is selected by default - just type and click OK
                        textbox.click(force=True)
                        textbox.fill(str(csgp_ref))
                        self.page.wait_for_timeout(500)

                        # Click OK button
                        ok_button = self.frame.get_by_role("button", name="OK").first
                        if ok_button.count() > 0:
                            smart_click(self.page, ok_button, "OK button")
                        else:
                            textbox.press("Enter")

                        # CRITICAL: Wait for table to reload with filtered data
                        # Wait for loading indicators first
                        try:
                            loading_indicator = self.frame.locator("[id*='loading'], [class*='loading'], .blockUI")
                            loading_indicator.wait_for(state="hidden", timeout=int(self.page_wait_time))
                        except:
                            pass  # No loading indicator found, that's fine

                        # DYNAMIC WAIT: Poll the table until it contains the filtered value
                        self.log(f"Waiting dynamically for table to show filtered data containing '{csgp_ref}'...")
                        max_wait_time = 30000  # Maximum 30 seconds
                        poll_interval = 500  # Check every 500ms
                        start_time = self.page.evaluate("Date.now()")

                        table_updated = False
                        while True:
                            # Check if we've exceeded max wait time
                            current_time = self.page.evaluate("Date.now()")
                            if current_time - start_time > max_wait_time:
                                self.log(f"Timeout waiting for table to update with '{csgp_ref}'", "warning")
                                break

                            # Get current table rows and check if they contain the filter value
                            try:
                                temp_table = self.frame.locator("#ctl00_phG_tab_t0_grid1_dataT0")
                                temp_rows = temp_table.locator("tbody tr")

                                if temp_rows.count() > 0:
                                    # Check if any row contains the CSGP ref
                                    for i in range(min(temp_rows.count(), 10)):  # Check first 10 rows
                                        row_text = temp_rows.nth(i).inner_text()
                                        if str(csgp_ref) in row_text:
                                            self.log(f"Table updated! Found '{csgp_ref}' in row {i} after {current_time - start_time}ms")
                                            table_updated = True
                                            break

                                if table_updated:
                                    break
                            except:
                                pass  # Continue polling

                            # Wait before next poll
                            self.page.wait_for_timeout(poll_interval)

                        # Additional small buffer after detecting the update
                        if table_updated:
                            self.page.wait_for_timeout(1000)  # 1 second buffer for stability

                        filter_success = True
                        self.log(f"[OK] Filtered Document Ref. with value '{csgp_ref}'")

            except Exception as e:
                self.log(f"Filter attempt failed: {e}", "error")

            if not filter_success:
                self.log(f"Could not filter by Document Ref. column", "warning")

            # Re-acquire table reference after filtering (table might have reloaded)
            table = None
            for selector in table_selectors:
                try:
                    test_table = self.frame.locator(selector)
                    if test_table.count() > 0:
                        table = test_table
                        self.log(f"Re-acquired table with selector: {selector}")
                        break
                except:
                    continue

            if not table:
                self.log("Could not re-acquire table after filtering", "warning")
                return []

            # Debug: Log the table HTML to understand structure
            try:
                table_html = table.evaluate("el => el.outerHTML")
                self.log(f"DEBUG: Table HTML length: {len(table_html)} chars", "debug")
                # Log a snippet of the HTML
                if len(table_html) < 500:
                    self.log(f"DEBUG: Table HTML: {table_html}", "debug")
                else:
                    self.log(f"DEBUG: Table HTML snippet: {table_html[:500]}...", "debug")
            except Exception as e:
                self.log(f"DEBUG: Could not get table HTML: {e}", "debug")

            # Get rows from the table - use same pattern as 1to1/group matching
            # The table variable already has the correct table (#ctl00_phG_tab_t0_grid1_dataT0)
            rows = table.locator("tbody tr")
            self.log(f"DEBUG: Getting rows from table using 'tbody tr'", "debug")

            if not rows:
                self.log(f"Could not find any rows in table", "warning")
                # Try to count all tr elements in the entire iframe as last resort
                try:
                    all_trs = self.frame.locator("tr")
                    tr_count = all_trs.count()
                    self.log(f"DEBUG: Total tr elements in iframe: {tr_count}", "debug")
                except:
                    pass
                return []

            row_count = rows.count()
            self.log(f"Table has {row_count} rows after filtering")

            # Debug: log first few rows
            if row_count > 0:
                for i in range(min(row_count, 3)):
                    try:
                        row_text = rows.nth(i).inner_text()
                        self.log(f"DEBUG: Row {i}: {row_text[:100]}", "debug")
                    except:
                        pass

            if row_count == 0 or self.is_table_empty(rows):
                self.log(f"No records found for Document Ref: {csgp_ref}", "warning")
                return []

            self.log(f"Found {row_count} matching records")

            # Extract record information - look for rows containing the CSGP ref
            matching_records = []
            
            # Find column indices for Receipt and Disbursement
            receipt_col_idx = -1
            disbursement_col_idx = -1
            orig_doc_col_idx = -1
            
            try:
                # Try to find headers in the entire frame, not just the data table
                headers = self.frame.locator(".GridHeader td, .GridHeader th, thead tr th")
                header_count = headers.count()
                
                if header_count > 0:
                    self.log(f"Found {header_count} headers in frame")
                    for i in range(header_count):
                        header_text = headers.nth(i).inner_text().strip()
                        if "Receipt" in header_text:
                            receipt_col_idx = i
                        elif "Disbursement" in header_text:
                            disbursement_col_idx = i
                        elif "Orig. Doc. Number" in header_text:
                            orig_doc_col_idx = i
                
                # Fallback to standard indices if not found (based on visual layout)
                if receipt_col_idx == -1: receipt_col_idx = 4
                if disbursement_col_idx == -1: disbursement_col_idx = 5
                if orig_doc_col_idx == -1: orig_doc_col_idx = 9
                
                self.log(f"[INFO] Column indices - Receipt: {receipt_col_idx}, Disbursement: {disbursement_col_idx}, OrigDoc: {orig_doc_col_idx}")
            except Exception as e:
                self.log(f"Error finding column indices: {e}", "warning")
                # Fallback
                receipt_col_idx = 4
                disbursement_col_idx = 5
                orig_doc_col_idx = 9

            for i in range(row_count):
                row = rows.nth(i)
                row_text = row.inner_text().strip()

                # Skip if row contains toolbar/button keywords
                skip_keywords = ["TOGGLE RECONCILED", "TOGGLE CLEARED", "RECONCILE PROCESSED", "CREATE ADJUSTMENT", "All Records"]
                if any(k in row_text for k in skip_keywords):
                    continue

                cells = row.locator("td")
                cell_count = cells.count()
                if cell_count < 3: continue

                # Check if this row contains the CSGP ref we're looking for (case-insensitive)
                if str(csgp_ref).lower() in row_text.lower():
                    
                    # Extract Document Ref from the row to use as description
                    document_ref = ""
                    receipt_amount = 0.0
                    disbursement_amount = 0.0
                    orig_doc_number = ""
                    
                    try:
                        # Document Ref is at index 6
                        if 6 < cell_count:
                            text = cells.nth(6).inner_text().strip()
                            if text: document_ref = text
                        
                        # Extract amounts
                        if receipt_col_idx != -1 and receipt_col_idx < cell_count:
                            val = cells.nth(receipt_col_idx).inner_text().strip().replace(",", "")
                            try: receipt_amount = float(val) 
                            except: pass
                                
                        if disbursement_col_idx != -1 and disbursement_col_idx < cell_count:
                            val = cells.nth(disbursement_col_idx).inner_text().strip().replace(",", "")
                            try: disbursement_amount = float(val)
                            except: pass

                        # Extract Original Doc Number
                        if orig_doc_col_idx != -1 and orig_doc_col_idx < cell_count:
                            orig_doc_number = cells.nth(orig_doc_col_idx).inner_text().strip()

                    except Exception as e:
                        self.log(f"Error extracting row data: {e}", "debug")

                    matching_records.append({
                        "row_index": i,
                        "description": document_ref or str(csgp_ref),
                        "row_locator": row,
                        "cell_count": cell_count,
                        "receipt": receipt_amount,
                        "disbursement": disbursement_amount,
                        "orig_doc_number": orig_doc_number
                    })
                    # Log at INFO level so we can debug user issues
                    self.log(f"[INFO] Row {i}: Ref='{document_ref}', Rec={receipt_amount}, Disb={disbursement_amount}, OrigDoc='{orig_doc_number}'")

            return matching_records

            return matching_records

        except Exception as e:
            self.log(f"Error searching Document Ref: {e}", "error")
            return []

    def validate_and_reconcile_reverse_ce_gl(self, matching_records: List[Dict], csgp_refs: List[str]) -> bool:
        """Validate and reconcile reverse CE/GL records based on exact opposite amounts."""
        try:
            record_count = len(matching_records)
            self.log(f"Validating {record_count} records for reconciliation")

            if record_count < 2:
                self.log(f"Insufficient records ({record_count}), need at least 2", "warning")
                return False

            records_to_reconcile = []
            
            # Check for exact opposite amounts in the SAME column
            # Case 1: Disbursement X and Disbursement -X
            # Case 2: Receipt X and Receipt -X
            
            import itertools
            found_pair = False
            
            # Helper to check if two floats are effectively opposite
            def is_opposite(v1, v2):
                if abs(v1) < 0.01 and abs(v2) < 0.01: return False # Ignore zero pairs
                return abs(v1 + v2) < 0.01 and abs(v1) > 0.01
            
            for r1, r2 in itertools.combinations(matching_records, 2):
                # Check Disbursement pair
                if is_opposite(r1['disbursement'], r2['disbursement']):
                    self.log(f"Found opposite pair in Disbursement: {r1['disbursement']} and {r2['disbursement']}")
                    records_to_reconcile = [r1, r2]
                    found_pair = True
                    break
                
                # Check Receipt pair
                if is_opposite(r1['receipt'], r2['receipt']):
                    self.log(f"Found opposite pair in Receipt: {r1['receipt']} and {r2['receipt']}")
                    records_to_reconcile = [r1, r2]
                    found_pair = True
                    break
            
            if not found_pair:
                self.log("No pair with exact opposite amounts found in the same column", "warning")
                # Optional: Log the values we saw
                for r in matching_records:
                    self.log(f"Row {r['row_index']}: R={r['receipt']}, D={r['disbursement']}", "debug")
                return False

            # Reconcile the selected records - Click the first cell (Reconciled column) directly
            self.log(f"Reconciling {len(records_to_reconcile)} records...")

            for idx, record in enumerate(records_to_reconcile):
                row = record["row_locator"]

                self.log(f"Processing record {idx+1}: {record.get('description', 'N/A')}")

                try:
                    # Get all cells in the row
                    cells = row.locator("td")
                    cell_count = cells.count()

                    if cell_count == 0:
                        self.log(f"No cells found in row {idx+1}", "error")
                        return False

                    self.log(f"DEBUG: Row {idx+1} has {cell_count} cells", "debug")

                    # Log first few cells to see which is which
                    for i in range(min(cell_count, 5)):
                        try:
                            cell_text = cells.nth(i).inner_text().strip()
                            self.log(f"DEBUG: Cell {i}: '{cell_text[:50] if cell_text else '(empty)'}'", "debug")
                        except:
                            pass

                    # The Reconciled checkbox is in the SECOND cell (index 1), not the first
                    # The first cell (index 0) is an empty selector/expander cell
                    if cell_count < 2:
                        self.log(f"Row doesn't have enough cells (need at least 2, found {cell_count})", "error")
                        return False

                    reconciled_cell = cells.nth(1)  # Second cell (index 1) is the Reconciled column

                    self.log(f"Clicking Reconciled column cell (cell 1) for record {idx+1}...")

                    # Scroll cell into view and highlight it for debugging
                    try:
                        reconciled_cell.scroll_into_view_if_needed(timeout=2000)
                        # Highlight the cell temporarily so we can see which one is being clicked
                        reconciled_cell.evaluate("el => { el.style.border = '3px solid red'; }")
                        self.page.wait_for_timeout(300)
                    except:
                        pass

                    # Try multiple click strategies
                    click_success = False
                    try:
                        # Strategy 1: Regular click on the cell
                        reconciled_cell.click(timeout=3000)
                        self.log(f"[OK] Clicked Reconciled cell for record {idx+1}")
                        click_success = True
                    except Exception as e1:
                        self.log(f"Regular click failed: {e1}", "debug")
                        try:
                            # Strategy 2: Force click on the cell
                            reconciled_cell.click(force=True, timeout=3000)
                            self.log(f"[OK] Force-clicked Reconciled cell for record {idx+1}")
                            click_success = True
                        except Exception as e2:
                            self.log(f"Force click failed: {e2}", "debug")
                            try:
                                # Strategy 3: JavaScript click on the cell
                                reconciled_cell.evaluate("el => el.click()")
                                self.log(f"[OK] JS-clicked Reconciled cell for record {idx+1}")
                                click_success = True
                            except Exception as e3:
                                self.log(f"JS click failed: {e3}", "debug")

                    if not click_success:
                        self.log(f"All click strategies failed for record {idx+1}", "error")
                        return False

                    # Wait for the UI to update
                    self.page.wait_for_timeout(800)

                except Exception as e:
                    self.log(f"Error processing record {idx+1}: {e}", "error")
                    return False

            # Save using Ctrl+S keyboard shortcut (more reliable than clicking button)
            self.log("Saving using Ctrl+S...")
            try:
                # Press Ctrl+S to save
                self.page.keyboard.press("Control+s")
                self.log("[OK] Pressed Ctrl+S to save")

                # Wait for save operation to complete
                smart_wait_for_page_load(self.page)
                self.log("[OK] Save operation completed")

            except Exception as save_error:
                self.log(f"Error pressing Ctrl+S: {save_error}", "error")
                return False

            self.log("[OK] Successfully reconciled reverse CE/GL records and saved")
            return True

        except Exception as e:
            self.log(f"Error during reconciliation: {e}", "error")
            return False

    def save_failed_entries(self):
        """Save failed entries to Excel file and return the file path if there are failures."""
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
            
            # Determine save path
            save_dir = os.getenv("SAVE_DIRECTORY")
            if save_dir:
                # Save to outputs folder in the run directory
                output_dir = Path(save_dir) / "outputs"
                output_dir.mkdir(parents=True, exist_ok=True)
                failed_entries_path = str(output_dir / "failed_entries.xlsx")
            else:
                # Fallback to current directory
                failed_entries_path = "failed_entries.xlsx"
                
            df.to_excel(failed_entries_path, index=False)
            self.log(f"[ERROR] Saved {len(self.failed_entries)} failed entries to {failed_entries_path}")
            return failed_entries_path
        else:
            self.log("[OK] No failed entries")
            return None
    
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
            login(self.page, self.website_url, self.username, self.password)
            self.log("[OK] Login successful")
            
            # STEP 3: Load match results
            self.log("=" * 60)
            self.log(f"STEP 3: Loading match results from {self.match_result_path}")
            self.log("=" * 60)
            dfs = pd.read_excel(
                self.match_result_path,
                sheet_name=["1to1 Matches", "Group Match"],
                dtype=str
            )
            self.log(f"[OK] Loaded {sum(len(df) for df in dfs.values())} total rows")

            # STEP 4: Process reverse CE/GL matches FIRST (if any)
            if "Group Match" in dfs:
                self.process_reverse_ce_gl_matches(dfs["Group Match"])

            # STEP 5: Navigate to Process Bank Records
            self.log("=" * 60)
            self.log("STEP 5: Navigating to Process Bank Records")
            self.log("=" * 60)
            navigatePage(self.page, "Process Bank Records")

            self.frame = self.wait_for_iframe()
            account_link = self.frame.get_by_role("link", name=self.account_name).last
            smart_click(self.page, account_link, f"Account link: {self.account_name}")
            self.page.wait_for_timeout(self.page_wait_time)
            self.log("[OK] Navigation successful")

            # STEP 6: Process 1-to-1 matches
            if "1to1 Matches" in dfs:
                self.process_1to1_matches(dfs["1to1 Matches"])

            # STEP 7: Process group matches (excluding reverse_ce_gl)
            if "Group Match" in dfs:
                self.process_group_matches(dfs["Group Match"])

            # STEP 8: Process matched items
            self.log("=" * 60)
            self.log("STEP 8: Processing matched items")
            self.log("=" * 60)
            process_button = self.page.locator("iframe[name=\"main\"]").content_frame.locator(
                "#ctl00_phDS_ds_ToolBar_ProcessMatched"
            ).get_by_text("Process")
            smart_click(self.page, process_button, "Process button")
            self.page.wait_for_timeout(self.page_wait_time)
            self.log("[OK] Matched items processed")

            # STEP 9: Save failed entries
            self.log("=" * 60)
            self.log("STEP 9: Saving failed entries")
            self.log("=" * 60)
            failed_entries_path = self.save_failed_entries()

            # Cleanup
            self.cleanup()

            # Send success notification
            self.send_pingback("completed")

            # Send email with attachment if there are failed entries
            try:
                if failed_entries_path:
                    reply_with_attachment(
                        reply_text="[OK] Match Statement process completed successfully.\n\n[WARNING] Some entries could not be matched automatically. Please review the attached failed_entries.xlsx file and process these manually.",
                        attachment_path=failed_entries_path
                    )
                else:
                    reply_to_trigger_email("[OK] Match Statement process completed successfully.\n\n[SUCCESS] All entries were matched successfully! No failed entries.")
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
                reply_to_trigger_email(f"[ERROR] Match Statement failed: {str(e)}")
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
    headless: bool = False,
    target_date: str = None 
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
        target_date: Target reconciliation date (DD/MM/YYYY)
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
        headless=headless,
        target_date=target_date
    )
    
    try:
        processor.run()
    finally:
        processor.cleanup()


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
