import pandas as pd
from playwright.sync_api import Playwright, sync_playwright, expect
import functions
import requests
from dotenv import load_dotenv
import os
from email_reply import reply_to_trigger_email, reply_with_attachment

# Load the .env file
load_dotenv()

def save_failed_entries(failed_entries, webhook_url=None):
    # Define the exact column order
    columns = [
        "Bank Statement Date", "Bank Transaction ID", "Bank Reference Number", "Bank Description",
        "Bank Receipt", "Bank Disbursement",
        "CSGP Transaction Date", "CSGP Reference", "CSGP Module", "CSGP Description",
        "CSGP Receipt", "CSGP Disbursement",
        "Amount Difference", "Date Difference", "Reason", "Confidence", "Match Type",
        "Bank_UID", "CSGP_UID"
    ]

    if failed_entries:
        df = pd.DataFrame(failed_entries)

        # Reorder columns to match the source format
        for col in columns:
            if col not in df.columns:
                df[col] = ""   # fill missing columns with empty strings

        df = df[columns]

        df.to_excel("failed_entries.xlsx", index=False)
        functions.log_message(webhook_url, f"❌ Saved {len(failed_entries)} failed entries to failed_entries.xlsx")
    else:
        functions.log_message(webhook_url, "✅ No failed entries found")

def is_table_empty(rows):
    row_count = rows.count()
    for i in range(row_count):
        row_text = rows.nth(i).inner_text().strip()
        if row_text and row_text not in ["0.00\n0.00", "No records found"]:
            return False
    return True

def false_filter_table(page, frame, header_text, textbox_selector, value):
    """
    Robust filter handler for ASPX grid tables.
    Clicks header, waits for textbox, retries twice if still hidden.
    """
    header = frame.locator("td.GridHeader.GridRow", has_text=header_text).first
    textbox = frame.locator(textbox_selector)

    max_attempts = 3
    for attempt in range(1, max_attempts + 1):
        functions.log_message(None, f"[INFO] Attempt {attempt}/{max_attempts} to activate filter for '{header_text}'")

        # Click the header cell to trigger filter input
        functions.highlight_and_click(page, header)
        page.wait_for_timeout(800)  # slight delay for render

        try:
            textbox.wait_for(state="attached", timeout=5000)

            # If it's attached but hidden, attempt reactivation
            if not textbox.is_visible():
                functions.log_message(None, f"[WARN] Filter textbox for '{header_text}' still hidden — forcing grid reactivation")
                frame.locator("table.GridHeader").first.click()
                page.wait_for_timeout(1000)
                functions.highlight_and_click(page, header)
                textbox.wait_for(state="visible", timeout=5000)

            # Once visible, fill and apply
            functions.highlight_and_click(page, textbox)
            textbox.fill(str(value))
            OK_button = frame.get_by_role("button", name="OK")
            functions.highlight(page, OK_button)
            textbox.clear()
            OK_button.click()
            page.wait_for_timeout(5000)
            return  # success
        except Exception as e:
            functions.log_message(None, f"[WARN] Attempt {attempt} failed for '{header_text}': {e}")
            page.wait_for_timeout(1000)
            continue

    # If all attempts fail, log and move on gracefully
    functions.log_message(None, f"[ERROR] Could not activate filter textbox for '{header_text}' after {max_attempts} tries")

def filter_table(page, frame, header_text, textbox_selector, value):
    """
    Clicks the table header, opens the filter textbox, enters the value,
    and applies the filter. Retries once if the textbox is hidden or not visible.
    """
    # 1. Locate header cell
    header = frame.locator("td.GridHeader.GridRow", has_text=header_text).first
    textbox = frame.locator(textbox_selector)

    # --- Attempt 1 ---
    functions.highlight_and_click(page, header)
    page.wait_for_timeout(500)  # slight pause to let filter appear

    # 2. Wait for filter textbox inside SAME frame
    try:
        textbox.wait_for(state="visible", timeout=5000)
    except Exception:
        # --- Attempt 2 (retry) ---
        functions.log_message(None, f"[WARN] Filter textbox for '{header_text}' not visible → retrying header click")
        functions.highlight_and_click(page, header)
        page.wait_for_timeout(1000)
        try:
            textbox.wait_for(state="visible", timeout=5000)
        except Exception as e:
            functions.log_message(None, f"[ERROR] Textbox for '{header_text}' still hidden after retry: {e}")
            return  # Skip this filter instead of crashing

    # Final check — textbox must be visible
    if not textbox.is_visible():
        functions.log_message(None, f"[ERROR] Textbox for '{header_text}' still hidden after retries, skipping.")
        return

    # 3. Fill textbox
    equals_button = frame.get_by_text("Equals", exact=True).first
    functions.highlight_and_click(page, equals_button)
    functions.highlight_and_click(page, textbox)
    textbox.fill(str(value))

    # 4. Click OK to apply filter
    OK_button = frame.get_by_role("button", name="OK")
    functions.highlight_and_click(page, OK_button)

    # 5. Small wait for grid to refresh
    page.wait_for_timeout(2000)

    functions.log_message(None, f"✅ Filtered '{header_text}' with value '{value}' successfully")

def click_matches(page, frame, csgp_ref, click_all=False, webhook_url=None):
    """
    Clicks checkbox(es) for a given CSGPRef.
    If click_all is True, clicks all checkboxes found.
    If click_all is False, clicks only the first one.
    Returns True if at least one checkbox was clicked, False otherwise.
    """

    # Re-select main frame before waiting
    frame = page.frame(name="main")
    textbox = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text")
    textbox.scroll_into_view_if_needed()

    try:
        # --- Ensure the textbox exists and is visible ---
        textbox.wait_for(state="visible", timeout=10000)
    except:
        functions.log_message(webhook_url, f"⚠️ Textbox not visible, re-focusing frame for {csgp_ref}")
        # Try refocusing iframe and reselecting textbox
        page.frame_locator("iframe[name='main']").locator("body").click()
        page.wait_for_timeout(1000)
        textbox = page.frame_locator("iframe[name='main']").locator(
            "#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text"
        )
        textbox.wait_for(state="visible", timeout=10000)

    # --- Safely click and fill textbox ---
    try:
        textbox.scroll_into_view_if_needed()
        textbox.click(force=True)
        textbox.fill(str(csgp_ref))
        page.wait_for_timeout(2000)
    except Exception as e:
        functions.log_message(webhook_url, f"❌ Failed to fill textbox for {csgp_ref}: {e}")
        return False

    # --- Proceed with table detection as before ---
    table_a = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
    table_b = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")

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
            functions.log_message(webhook_url, f"⚠️ No detail table found for {csgp_ref}")
            return False

    # --- Robust "Nothing found" check ---
    if detail_table.locator("td:has-text('Nothing has been found')").count() > 0:
        functions.log_message(webhook_url, f"  ⚠️ No matches found in table for {csgp_ref}, skipping")
        return False

    # --- Detect empty/placeholder rows ---
    rows = detail_table.locator("tr")
    if is_table_empty(rows):
        functions.log_message(webhook_url, f"  ⚠️ Table visible but empty for {csgp_ref}, skipping")
        return False

    # --- Identify real data rows (skip header) ---
    data_rows = detail_table.locator("tbody tr")
    row_count = data_rows.count()
    functions.log_message(webhook_url, f"  Found {row_count} data rows in detail table (Type {table_type})")

    if row_count < 2:
        functions.log_message(webhook_url, f"  ⚠️ Not enough rows to click (need at least 2) for {csgp_ref}")
        return False

    # --- Target the second column ---
    target_row = data_rows.nth(0)
    second_col = target_row.locator("td").nth(1)

    if second_col.count() == 0:
        functions.log_message(webhook_url, f"  ⚠️ Second column not found in row 2 for {csgp_ref}")
        return False

    functions.log_message(webhook_url, f"  ✅ Clicking 2nd column of 2nd row in Type {table_type} table")
    functions.highlight_and_click(page, second_col)
    page.wait_for_timeout(1000)

    return True

def searchMainTable(page, frame, row_data, failed_entries, webhook_url=None):
    filter_table(page, frame, "Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", row_data["Bank Reference Number"])
    # filter_table(page, frame, "Receipt", "#ctl00_phG_PXSplitContainer_grid1_fd_num1", row_data["Bank Receipt"])

    table = frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
    rows = table.locator("tbody tr")
    row_count = rows.count()
    functions.log_message(webhook_url, f"Found {row_count} rows")

    if is_table_empty(rows):
        functions.log_message(webhook_url, "  ⚠️ No records found (all rows empty) → marking as failed")
        failed_entries.append(row_data)
        return

    # --- Always click the first row ---
    if row_count > 0:
        row = rows.nth(0)
        first_col = row.locator("td").nth(0)
        try:
            value = first_col.inner_text()
        except:
            value = "<empty>"
        page.wait_for_timeout(3000)
        functions.log_message(webhook_url, f"  Processing FIRST row, first_col={value}")
        click_matches(page, frame, row_data["CSGP Reference"])
        return  # Done after first row

    # If no rows found
    functions.log_message(webhook_url, "⚠️ No valid rows found → marking as failed")
    failed_entries.append(row_data)

def enableMultipleMatching(page, frame, webhook_url=None):
    """
    Clicks the 'Allow Multiple Matching' checkbox if available.
    Only one of Type A or Type B will exist.
    """
    try:
        checkbox_a = frame.locator(
            "#ctl00_phG_PXSplitContainer_tab2_t1_frmCreateDocumentInv_edMultipleMatching_text"
        )
        if checkbox_a.count() > 0:
            if not checkbox_a.first.is_checked():
                functions.log_message(webhook_url, "🔘 Enabling Multiple Matching (Type A)")
                functions.highlight_and_click(page, checkbox_a.first)
            else:
                functions.log_message(webhook_url, "✅ Multiple Matching (Type A) already enabled")
            return
    except Exception as e:
        functions.log_message(webhook_url, f"⚠️ Skipped Type A: {e}")

    try:
        checkbox_b = frame.locator(
            "#ctl00_phG_PXSplitContainer_tab2_t0_frmMatchToPayments_edMultipleMatchingToPayments_text"
        )
        if checkbox_b.count() > 0:
            if not checkbox_b.first.is_checked():
                functions.log_message(webhook_url, "🔘 Enabling Multiple Matching (Type B)")
                functions.highlight_and_click(page, checkbox_b.first)
            else:
                functions.log_message(webhook_url, "✅ Multiple Matching (Type B) already enabled")
            return
    except Exception as e:
        functions.log_message(webhook_url, f"⚠️ Skipped Type B: {e}")


    functions.log_message(webhook_url, "⚠️ No Multiple Matching checkbox found")
    
def checkGroupMatchExists(page, frame, csgp_ref, webhook_url=None):
    """
    Dry run: return True if the CSGPRef exists and has a checkbox row.
    """
    textbox = page.frame_locator("iframe[name='main']").locator(
        "#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text"
    )
    try:
        functions.highlight_and_click(page, textbox)
        textbox.fill(str(csgp_ref))
        page.keyboard.press("Enter")
        page.wait_for_timeout(2000)
        # textbox.clear()
    except:
        functions.log_message(webhook_url, f"  ⚠️ Could not access textbox for {csgp_ref}")
        return False

    # Try Type A
    table_a = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
    # Try Type B
    table_b = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")

    detail_table = None
    try:
        table_a.wait_for(state="visible", timeout=2000)
        detail_table = table_a
    except:
        try:
            table_b.wait_for(state="visible", timeout=2000)
            detail_table = table_b
        except:
            return False

    if detail_table.locator("td:has-text('Nothing has been found')").count() > 0:
        return False

    # look for real rows with checkboxes
    real_rows = detail_table.locator("tr:has(td input[type=checkbox])")
    return real_rows.count() > 0

def groupMatchLogic(page, frame, row_data, bank_ref, csgp_refs, failed_entries, webhook_url=None):
    functions.log_message(webhook_url, f"[Group] Searching main table for BankRef={bank_ref}")

    # --- Step 1: Filter by BankRef (same as searchMainTable) ---
    filter_table(page, frame, "Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", bank_ref)

    # --- Step 2: Validate main table result ---
    table = frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
    rows = table.locator("tbody tr")

    if is_table_empty(rows):
        functions.log_message(webhook_url, f"[Group] ❌ No usable rows for BankRef={bank_ref} → marking as failed")
        failed_entries.append(row_data)
        return

    # --- Step 3: Click the first row for each CSGPRef ---
    enableMultipleMatching(page, frame)
    page.wait_for_timeout(1000)

    for ref in csgp_refs:
        functions.log_message(webhook_url, f"[Group] Clicking FIRST row for CSGPRef={ref}")
        # Instead of filtering by CSGPRef, just click the first row
        textbox = page.frame_locator("iframe[name='main']").locator(
            "#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_at_tlb_fb_text"
        )
        try:
            functions.highlight_and_click(page, textbox)
            textbox.fill(str(ref))
            page.keyboard.press("Enter")
            page.wait_for_timeout(2000)
            # textbox.clear()
        except:
            functions.log_message(webhook_url, f"  ⚠️ Could not access textbox for {ref}")

        # Try Type A table
        table_a = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
        # Try Type B table
        table_b = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t0_PXGrid1_dataT0")

        detail_table = None
        try:
            table_a.wait_for(state="visible", timeout=3000)
            detail_table = table_a
        except:
            try:
                table_b.wait_for(state="visible", timeout=3000)
                detail_table = table_b
            except:
                functions.log_message(webhook_url, f"⚠️ No detail table found for {ref}")
                continue

        # --- Always click the first real row with a checkbox ---
        real_rows = detail_table.locator("tr:has(td input[type=checkbox])")
        real_count = real_rows.count()
        if real_count > 0:
            row = real_rows.nth(0)
            checkbox_cell = row.locator("td input[type=checkbox]")
            if checkbox_cell.count() > 0:
                cell = checkbox_cell.first
                if not cell.is_checked():
                    functions.log_message(webhook_url, f"  ✅ Clicking checkbox in first row for {ref}")
                    functions.highlight_and_click(page, cell)
                detail_table.wait_for(timeout=3000)
            else:
                functions.log_message(webhook_url, f"  ⚠️ No checkbox in first row for {ref}")
        else:
            functions.log_message(webhook_url, f"  ⚠️ No usable rows for {ref}, skipping")

    functions.log_message(webhook_url, f"[Group] ✅ Finished group match for BankRef={bank_ref}")

def checkPossibleMatchExists(page, frame, ref, verified_refs, row_data, failed_entries, webhook_url=None):
    false_filter_table(page, frame, "Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", ref)

    # Wait for rows
    table = frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
    rows = table.locator("tbody tr")
    row_count = rows.count()
    functions.log_message(webhook_url, f"[Possible] Found {row_count} rows for BankRef={ref}")

    # Check for empty
    if is_table_empty(rows):
        functions.log_message(webhook_url, f"[Possible] ❌ No usable rows for BankRef={ref} → marking as failed")
        failed_entries.append(row_data)
        return
    else:
        functions.log_message(webhook_url, f"[Possible] ✅ Verified BankRef={ref} exists")
        verified_refs.append(ref)

def checkCSGPMatchExists(page, frame, csgp_ref, row_data, failed_entries, webhook_url=None):
    """
    Verifies if a given CSGPRef exists in the CSGP table.
    Returns True if found, False otherwise.
    """
    functions.log_message(webhook_url, f"[Possible] Checking availability for CSGPRef={csgp_ref}")

    false_filter_table(page, frame, "Document Ref.", "#ctl00_phG_tab_t0_grid1_fd_txt", csgp_ref)
    page.wait_for_timeout(3000)

    # Wait for rows
    table = frame.locator("#ctl00_phG_tab_t0_grid1_dataT0")
    rows = table.locator("tbody tr")
    row_count = rows.count()
    functions.log_message(webhook_url, f"[Possible] Found {row_count} rows for CSGPRef={csgp_ref}")

    # Check if table is empty or useless
    if is_table_empty(rows):
        functions.log_message(webhook_url, f"[Possible] ❌ No usable rows for CSGPRef={csgp_ref} → marking as failed")
        failed_entries.append(row_data)
        return False
    else:
        functions.log_message(webhook_url, f"[Possible] ✅ Verified CSGPRef={csgp_ref} exists")
        return True

def clickPossibleMatches(page, frame, ref):
    false_filter_table(page, frame, "Ext. Ref. Nbr.", "#ctl00_phG_PXSplitContainer_grid1_fd_txt", ref)

    # Select by clicking selector column
    table = frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
    row = table.locator("tbody tr").nth(0)
    selector_col = row.locator("td").nth(3)  # 0-based index; 3 = 4th column
    return selector_col

def possibleMatchLogic(page, frame, row_data, bank_refs, csgp_ref, accountName, failed_entries, webhook_url=None):
    functions.log_message(webhook_url, f"[Possible] Starting with BankRefs={bank_refs}, CSGPRef={csgp_ref}")

    verified_refs = []

    # --- Step 1: Verify all BankRefs exist ---
    for ref in bank_refs:
        functions.log_message(webhook_url, f"[Possible] Verifying BankRef={ref}")

        checkPossibleMatchExists(page, frame, ref, verified_refs, row_data, failed_entries, webhook_url)

    # If not all verified → fail
    if len(verified_refs) != len(bank_refs):
        functions.log_message(webhook_url, "[Possible] ❌ Some BankRefs could not be verified → aborting")
        failed_entries.append(row_data)
        return

    # --- Step 2: Search for the CSGPRef ---
    functions.navigatePage(page, "Reconciliation Statements")
    frame = functions.wait_for_iframe(page)
    page.wait_for_timeout(2000)
    functions.click_account_name(page, frame, accountName)
    page.wait_for_timeout(3000)

    functions.log_message(webhook_url, f"[Possible] Searching for CSGPRef={csgp_ref}")

    if not checkCSGPMatchExists(page, frame, csgp_ref, row_data, failed_entries, webhook_url):
        return  # stop early if no valid rows found

    # ✅ Define table here before using it
    table = frame.locator("#ctl00_phG_tab_t0_grid1_dataT0")

    # Table body rows that are NOT headers
    row = table.locator("tbody tr").filter(
        has_not=frame.locator("td.GridHeader")
    ).nth(0)

    selector_col = row.locator("td").nth(1)  # 0-based index; 1 = 2nd column
    functions.highlight(page, selector_col)

    functions.log_message(webhook_url, f"[Possible] ✅ Selected CSGPRef={csgp_ref}")

    functions.navigatePage(page, "Process Bank Records")
    # Wait until iframe is ready
    frame = functions.wait_for_iframe(page)
    page.wait_for_timeout(2000)
    # click the last occurrence of the account name link
    functions.click_account_name(page, frame, accountName)
    page.wait_for_timeout(20000)

    # --- Step 3: Select all verified BankRefs ---
    for ref in verified_refs:
        functions.log_message(webhook_url, f"[Possible] Selecting BankRef={ref}")

        checkbox_col = clickPossibleMatches(page, frame, ref)
        if checkbox_col.count() > 0:
            functions.log_message(webhook_url, f"[Possible] ✅ Clicking selector column for BankRef={ref}")
            functions.highlight_and_click(page, checkbox_col)
        else:
            functions.log_message(webhook_url, f"[Possible] ⚠️ Could not find selector column for {ref}")
            failed_entries.append(row_data)
            return

    # # Click Hide (TODO by you) 
    # functions.log_message(webhook_url, "[Possible] TODO: Click Hide here")

    # Navigate to CSGP section
    functions.navigatePage(page, "Reconciliation Statements")
    # Wait until iframe is ready
    frame = functions.wait_for_iframe(page)
    page.wait_for_timeout(2000)
    # click the last occurrence of the account name link
    functions.click_account_name(page, frame, accountName)
    page.wait_for_timeout(20000)

    # Step 4: Select the CSGPRef
    functions.log_message(webhook_url, f"[Possible] Searching for CSGPRef={csgp_ref}")
    false_filter_table(page, frame, "Document Ref.", "#ctl00_phG_tab_t0_grid1_fd_txt", csgp_ref)

    # Make sure you're pointing to the right grid body
    table = frame.locator("#ctl00_phG_tab_t0_grid1_dataT0")

    # Grab only visible rows
    rows = table.locator("tbody tr:visible")

    if rows.count() == 0:
        print("[WARN] No rows found in grid")
    else:
        # Skip filter/header row → start with nth(1)
        row = rows.nth(1) if rows.count() > 1 else rows.nth(0)

        # Get selector column
        selector_col = row.locator("td").nth(1)  # 0-based index; 1 = 2nd column

        functions.highlight_and_click(page, selector_col)

    # Reconcile Statement 
    reconcile_button = page.frame_locator("iframe[name='main']").locator("#aspnetForm > div:nth-child(25)")
    functions.highlight(page, reconcile_button)
    functions.log_message(webhook_url, "[Possible]Click Reconcile Statement")

    functions.log_message(webhook_url, f"[Possible] ✅ Finished Possible Match for CSGPRef={csgp_ref}")

    functions.navigatePage(page, "Process Bank Records")

    # Wait until iframe is ready
    frame = functions.wait_for_iframe(page)
    page.wait_for_timeout(2000)
    # click the last occurrence of the account name link
    functions.click_account_name(page, frame, accountName)
    page.wait_for_timeout(20000)

def process_sheet(sheet_name, df, page, accountName, failed_entries, webhook_url=None):
    frame = functions.wait_for_iframe(page)
    """
    Process a single sheet from the Excel file.
    Different logic can be added depending on the sheet.
    """
    for index, row in df.iterrows():
        bank_reference_number = row.get("Bank Reference Number")
        csgp_ref = row.get("CSGP Reference")

        # Skip if either field is empty/NaN
        if pd.isna(bank_reference_number) or pd.isna(csgp_ref) or str(bank_reference_number).strip() == "" or str(csgp_ref).strip() == "":
            continue

        # # Extract all columns into variables
        # bank_statement_date   = row.get("Bank Statement Date")
        # bank_reference_number = row.get("Bank Reference Number")
        # bank_description      = row.get("Bank Description")
        # bank_receipt          = row.get("Bank Receipt")
        # bank_disbursement     = row.get("Bank Disbursement")
        # csgp_transaction_date = row.get("CSGP Transaction Date")
        # csgp_module           = row.get("CSGP Module")
        # csgp_description      = row.get("CSGP Description")
        # csgp_receipt          = row.get("CSGP Receipt")
        # csgp_disbursement     = row.get("CSGP Disbursement")
        # amount_difference     = row.get("Amount Difference")
        # date_difference       = row.get("Date Difference")
        # reason                = row.get("Reason")
        # confidence            = row.get("Confidence")
        # match_type            = row.get("Match Type")
        # bank_uid              = row.get("Bank_UID")
        # csgp_uid              = row.get("CSGP_UID")

        # Do something depending on the sheet
        if sheet_name == "1to1 Matches":
            functions.log_message(webhook_url, f"[1to1] Row {index+1}: BankRef={bank_reference_number}, CSGPRef={csgp_ref}")

            searchMainTable(page, frame, row, failed_entries, webhook_url)

        elif sheet_name == "Group Match":
            functions.log_message(webhook_url, f"[Group] Row {index+1}: BankRef={bank_reference_number}, CSGPRef={csgp_ref}")

            # Split BankRef (take only first if multiple)
            bank_ref_raw = str(row.get("Bank Reference Number", "")).strip()
            bank_ref = bank_ref_raw.split(",")[0].strip() if bank_ref_raw else None

            # Split CSGP refs (loop through all)
            csgp_ref_raw = str(row.get("CSGP Reference", "")).strip()
            csgp_refs = [ref.strip() for ref in csgp_ref_raw.split(",") if ref.strip()] if csgp_ref_raw else []

            functions.log_message(webhook_url, f"[Group] Row {index+1}: BankRef={bank_ref}, CSGPRefs={csgp_refs}")

            groupMatchLogic(page, frame, row, bank_ref, csgp_refs, failed_entries, webhook_url)

        elif sheet_name == "Possible Match":
            functions.log_message(webhook_url, f"[Possible] Row {index+1}: BankRef={bank_reference_number}, CSGPRef={csgp_ref}")
            
            # --- Split Bank Refs into list ---
            bank_refs = []
            if pd.notna(bank_reference_number):
                bank_refs = [ref.strip() for ref in str(bank_reference_number).split(",") if ref.strip()]
            
            # --- Take only the first CSGP Ref ---
            main_csgp_ref = None
            if pd.notna(csgp_ref):
                main_csgp_ref = str(csgp_ref).split(",")[0].strip()
            
            functions.log_message(webhook_url, f"[Possible] Parsed BankRefs={bank_refs}, Main CSGPRef={main_csgp_ref}")

            possibleMatchLogic(page, frame, row, bank_refs, main_csgp_ref, accountName, failed_entries, webhook_url)
        
    if sheet_name == "1to1 Matches" or sheet_name == "Group Match":
        # After processing all rows in 1to1 or Group Match, click Process
        functions.log_message(webhook_url, f"Clicking Process button for {sheet_name}")
        
        process_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_ProcessMatched").get_by_text("Process")
        functions.highlight(page, process_button)

def run_match_process(
    playwright: Playwright,
    matchresultpath,
    website_url=os.getenv("WEBSITE_URL"),
    username=os.getenv("WEBSITE_USERNAME"),
    password=os.getenv("PASSWORD"),
    accountName=os.getenv("accountName"),
    pingback_url=None,
    payload=None,
    webhook_url=None
):
    try:
        failed_entries = []
        functions.send_pingback(pingback_url, requests, "started", payload)
        browser = playwright.chromium.launch(headless=False)
        page = browser.new_page()
        functions.login(page, website_url, username, password)
        functions.navigatePage(page, "Process Bank Records")
        frame = functions.wait_for_iframe(page)
        accountName_link = frame.get_by_role("link", name=accountName).last
        functions.highlight_and_click(page, accountName_link)
        page.wait_for_timeout(5000)
        dfs = pd.read_excel(matchresultpath, sheet_name=["1to1 Matches", "Group Match", "Possible Match"])
        # dfs = pd.read_excel("dummydata.xlsx", sheet_name=["1to1 Matches", "Group Match"])
        for sheet_name, df in dfs.items():
            print("Columns in downloaded Excel:", df.columns.tolist())
            functions.log_message(webhook_url, f"\n--- Processing {sheet_name} ---")
            process_sheet(sheet_name, df, page, accountName, failed_entries, webhook_url)
        save_failed_entries(webhook_url=webhook_url, failed_entries=failed_entries)
        dfs = pd.read_excel(matchresultpath, sheet_name=["Possible Match"])
        for sheet_name, df in dfs.items():
            functions.log_message(webhook_url, f"\n--- Processing {sheet_name} ---")
            process_sheet(sheet_name, df, page, accountName, failed_entries, webhook_url)
        browser.close()
        save_failed_entries(webhook_url=webhook_url, failed_entries=failed_entries)
        functions.send_pingback(pingback_url, requests, "completed", payload)
        output_file = "failed_entries.xlsx"

        reply_with_attachment(
            reply_text="✅ Match Statement process completed successfully. Please find the attached file.",
            attachment_path=output_file
        )
    except Exception as e:
        functions.send_pingback(pingback_url, requests, "failed", payload, error=str(e))
        reply_to_trigger_email("Match Statement failed.")
        raise

if __name__ == "__main__":
    # Default to config.py for direct execution
    import config
    with sync_playwright() as playwright:
        run_match_process(
            playwright,
            config.website_url,
            config.username,
            config.password,
            config.accountName,
            config.matchresultpath,
            pingback_url=None,
            payload=None,
            webhook_url=None
        )