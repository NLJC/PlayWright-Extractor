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
        self.failed_bank_refs: Set[str] = set()  # Track failed BankRefs to prevent duplicates
        
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
            match_type = str(row.get("Match Type", "")).strip().lower()

            if not bank_ref_raw or not csgp_ref_raw:
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

            # Enable multiple matching
            self.enable_multiple_matching()
            self.page.wait_for_timeout(1000)

            # Match each CSGP ref
            for csgp_ref in csgp_refs:
                self.log(f"[Group] Matching CSGPRef={csgp_ref}")
                self.search_and_match_csgp_ref(csgp_ref)

        self.log(f"✅ Completed group matches")

    def process_reverse_ce_gl_matches(self, df: pd.DataFrame):
        """STEP 6.5: Process reverse CE/GL matches in Acumatica."""
        self.log("=" * 60)
        self.log(f"STEP 6.5: Processing Reverse CE/GL Matches ({len(df)} rows)")
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

            # Navigate to CashBook -> Account -> Reconciliation Statements
            success = self.navigate_to_reconciliation_statements()
            if not success:
                self.log(f"Failed to navigate to Reconciliation Statements for {csgp_refs}", "error")
                self.failed_entries.append(row.to_dict())
                continue

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

            # Navigate back to Process Bank Records
            self.log("Navigating back to Process Bank Records...")
            functions.navigatePage(self.page, "Process Bank Records")
            self.frame = self.wait_for_iframe()
            account_link = self.frame.get_by_role("link", name=self.account_name).last
            self.smart_click(account_link, f"Account link: {self.account_name}")
            self.page.wait_for_timeout(3000)

        self.log(f"✅ Completed reverse_ce_gl matches")

    def navigate_to_reconciliation_statements(self) -> bool:
        """Navigate to CashBook -> Reconciliation Statements -> Account."""
        try:
            self.log("Navigating to CashBook...")

            # Click on CashBook in the menu (similar to navigatePage function)
            cashbook_link = self.page.locator("div").filter(has_text=re.compile(r"^Cash Book$")).first
            self.smart_click(cashbook_link, "CashBook menu")
            self.page.wait_for_timeout(1000)

            # Click on "Reconciliation Statements" button
            self.log("Clicking Reconciliation Statements button...")
            recon_button = self.page.get_by_role("link", name="Reconciliation Statements")
            recon_button.hover()
            self.page.wait_for_timeout(1000)
            self.smart_click(recon_button, "Reconciliation Statements button")
            self.page.wait_for_timeout(5000)

            # Wait for iframe
            self.frame = self.wait_for_iframe()

            # Now select the account (e.g., CIM02) from the dropdown or link
            self.log(f"Selecting account: {self.account_name}")

            # Try to find account link in the iframe
            account_link = self.frame.get_by_role("link", name=self.account_name)

            if account_link.count() == 0:
                # Try alternate selector - might be a dropdown
                account_link = self.frame.locator(f"a:has-text('{self.account_name}')").first

            if account_link.count() > 0:
                self.smart_click(account_link, f"Account: {self.account_name}")
                self.page.wait_for_timeout(3000)
            else:
                self.log(f"Could not find account link for {self.account_name}", "warning")
                return False

            self.log("✅ Successfully navigated to Reconciliation Statements")
            return True

        except Exception as e:
            self.log(f"Failed to navigate to Reconciliation Statements: {e}", "error")
            return False

    def search_document_ref_in_reconciliation(self, csgp_ref: str) -> List[Dict]:
        """Search for CSGP reference in Document Ref column and return matching records."""
        try:
            self.log(f"Searching for Document Ref: {csgp_ref}")

            # Wait a bit for page to fully load
            self.page.wait_for_timeout(2000)

            # Try multiple possible table selectors
            table = None
            table_selectors = [
                "#ctl00_phG_tab_t0_grid_dataT0",
                "#ctl00_phG_grid_dataT0",
                "table[id*='grid'][id*='dataT0']"
            ]

            for selector in table_selectors:
                try:
                    test_table = self.frame.locator(selector)
                    test_table.wait_for(state="visible", timeout=3000)
                    table = test_table
                    self.log(f"Found table with selector: {selector}")
                    break
                except:
                    continue

            if not table:
                self.log("Could not find reconciliation table with any known selector", "warning")
                return []

            # Filter by Document Ref column - try different header texts
            try:
                self.filter_table("Document Ref.", "#ctl00_phG_tab_t0_grid_fd_txt", csgp_ref)
            except:
                try:
                    self.filter_table("Document Ref", "#ctl00_phG_grid_fd_txt", csgp_ref)
                except Exception as e:
                    self.log(f"Could not filter by Document Ref: {e}", "warning")

            self.page.wait_for_timeout(2000)

            # Get all rows
            rows = table.locator("tbody tr")
            row_count = rows.count()

            if row_count == 0 or self.is_table_empty(rows):
                self.log(f"No records found for Document Ref: {csgp_ref}", "warning")
                return []

            self.log(f"Found {row_count} matching records")

            # Extract record information
            matching_records = []
            for i in range(row_count):
                row = rows.nth(i)
                cells = row.locator("td")
                cell_count = cells.count()

                # Extract description from various possible column positions
                description = ""
                try:
                    # Try different column indices for description
                    for col_idx in [2, 3, 4]:
                        if col_idx < cell_count:
                            desc = cells.nth(col_idx).inner_text().strip()
                            if desc and desc not in ["0.00", "", "N/A"]:
                                description = desc
                                break
                except:
                    pass

                matching_records.append({
                    "row_index": i,
                    "description": description,
                    "row_locator": row
                })

            return matching_records

        except Exception as e:
            self.log(f"Error searching Document Ref: {e}", "error")
            return []

    def validate_and_reconcile_reverse_ce_gl(self, matching_records: List[Dict], csgp_refs: List[str]) -> bool:
        """Validate and reconcile reverse CE/GL records based on count and description."""
        try:
            record_count = len(matching_records)
            self.log(f"Validating {record_count} records for reconciliation")

            # Check if there are more than 2 records
            if record_count > 2:
                self.log("More than 2 records found, checking descriptions...")

                # Get first record's description
                first_description = matching_records[0]["description"]

                # Find first matching pair (same description)
                matching_pair = None
                for i in range(1, record_count):
                    if matching_records[i]["description"] == first_description:
                        matching_pair = [matching_records[0], matching_records[i]]
                        break

                if not matching_pair:
                    self.log("No matching descriptions found in first 2 pairs", "warning")
                    return False

                records_to_reconcile = matching_pair

            elif record_count == 2:
                self.log("Exactly 2 records found, proceeding to reconcile")
                records_to_reconcile = matching_records

            else:
                self.log(f"Insufficient records ({record_count}), need at least 2", "warning")
                return False

            # Reconcile the selected records
            self.log(f"Reconciling {len(records_to_reconcile)} records...")

            for record in records_to_reconcile:
                row = record["row_locator"]

                # Find the Reconciled checkbox - try multiple strategies
                reconciled_checkbox = None

                # Strategy 1: Look for checkbox in first few columns
                for col_idx in range(5):  # Check first 5 columns
                    try:
                        checkbox = row.locator("td").nth(col_idx).locator("input[type='checkbox']")
                        if checkbox.count() > 0:
                            reconciled_checkbox = checkbox.first
                            self.log(f"Found checkbox in column {col_idx}")
                            break
                    except:
                        continue

                # Strategy 2: Look for any checkbox in the row
                if not reconciled_checkbox:
                    try:
                        checkbox = row.locator("input[type='checkbox']")
                        if checkbox.count() > 0:
                            reconciled_checkbox = checkbox.first
                            self.log("Found checkbox using generic selector")
                    except:
                        pass

                if reconciled_checkbox:
                    # Check if not already checked
                    try:
                        if not reconciled_checkbox.is_checked():
                            self.smart_click(reconciled_checkbox, "Reconciled checkbox")
                            self.page.wait_for_timeout(500)
                        else:
                            self.log("Checkbox already checked, skipping")
                    except Exception as e:
                        self.log(f"Error clicking checkbox: {e}", "warning")
                        return False
                else:
                    self.log("Could not find Reconciled checkbox", "warning")
                    return False

            # Click Save button - try multiple selectors
            save_button = None
            save_selectors = [
                "#ctl00_phG_tab_t0_tlbDataBar_btnSave",
                "#ctl00_phG_tlbDataBar_btnSave",
                "a[id*='btnSave']",
                "button:has-text('Save')"
            ]

            for selector in save_selectors:
                try:
                    btn = self.frame.locator(selector)
                    if btn.count() > 0:
                        save_button = btn.first
                        self.log(f"Found Save button with selector: {selector}")
                        break
                except:
                    continue

            if not save_button:
                # Try by role
                save_button = self.frame.get_by_role("button", name="Save")

            if save_button and save_button.count() > 0:
                self.smart_click(save_button, "Save button")
                self.page.wait_for_timeout(3000)
            else:
                self.log("Could not find Save button", "warning")
                return False

            self.log("✅ Successfully reconciled reverse CE/GL records")
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
            failed_entries_path = "failed_entries.xlsx"
            df.to_excel(failed_entries_path, index=False)
            self.log(f"❌ Saved {len(self.failed_entries)} failed entries to {failed_entries_path}")
            return failed_entries_path
        else:
            self.log("✅ No failed entries")
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

                # STEP 6.5: Process reverse CE/GL matches
                self.process_reverse_ce_gl_matches(dfs["Group Match"])

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
            failed_entries_path = self.save_failed_entries()

            # Cleanup
            self.cleanup()

            # Send success notification
            self.send_pingback("completed")

            # Send email with attachment if there are failed entries
            try:
                if failed_entries_path:
                    reply_with_attachment(
                        reply_text="✅ Match Statement process completed successfully.\n\n⚠️ Some entries could not be matched automatically. Please review the attached failed_entries.xlsx file and process these manually.",
                        attachment_path=failed_entries_path
                    )
                else:
                    reply_to_trigger_email("✅ Match Statement process completed successfully.\n\n🎉 All entries were matched successfully! No failed entries.")
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
