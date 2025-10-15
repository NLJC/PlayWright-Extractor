import re
from playwright.sync_api import Playwright, sync_playwright, expect
import functions
from ExcelFilter import process_bank_transactions
import requests
import pandas as pd
import config

def handle_detail_table(page, frame, webhook_url=None):
    # Try Type A table
    table_a = frame.locator("#ctl00_phG_PXSplitContainer_tab2_t1_gridDetailMatches4_dataT0")
    # Try Type B table
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
            functions.log_message(webhook_url, "⚠️ No detail table found")
            return

    rows = detail_table.locator("tr")
    row_count = rows.count()
    functions.log_message(webhook_url, f"  Found {row_count} rows in detail table (Type {table_type})")

    for j in range(row_count):
        row = rows.nth(j)
        relevance_cell = row.locator("td").nth(2)
        # Check if the cell is visible before highlighting or reading text
        try:
            if not relevance_cell.is_visible():
                continue
            functions.highlight(page, relevance_cell)
            relevance_text = relevance_cell.inner_text().strip()
        except Exception as e:
            functions.log_message(webhook_url, f"  Row {j} → relevance cell not visible or error: {e}")
            continue

        try:
            relevance = float(relevance_text.replace(",", ""))
        except ValueError:
            functions.log_message(webhook_url, f"  Row {j} → invalid relevance: {relevance_text}")
            continue

        functions.log_message(webhook_url, f"  Row {j} → relevance: {relevance}")

        if relevance >= 90:
            if table_type == "A":
                # Type A: checkbox in td.nth(1)
                checkbox_cell = row.locator("td").nth(1)
                functions.log_message(webhook_url, f"  ✅ Clicking Type A checkbox in row {j}")
                functions.highlight_and_click(page, checkbox_cell)
                table_a.wait_for(timeout=3000)

            elif table_type == "B":
                # Type B: checkbox also in td.nth(1) but structure differs
                checkbox_cell = row.locator("td").nth(1)
                functions.log_message(webhook_url, f"  ✅ Clicking Type B checkbox in row {j}")
                functions.highlight_and_click(page, checkbox_cell)
                table_b.wait_for(timeout=3000)

            break  # stop scanning after first valid row

def CAMatchExtract(
    playwright: Playwright,
    website_url=config.website_url,
    username=config.username,
    password=config.password,
    accountName=config.accountName,
    save_path=config.save_path,
    CAMatchOutputFile=config.CAMatchOutputFile,
    allowed_types=config.allowed_types,
    pingback_url=None,
    payload=None,
    webhook_url=None
):
    try:
        functions.send_pingback(pingback_url, "started", requests = requests, payload = payload)
        # open browser
        browser = playwright.chromium.launch(headless=False)
        # Create browser and context with downloads enabled
        context = browser.new_context(
            accept_downloads=True   # ✅ this allows file downloads
        )

        page = context.new_page()
        # Login
        functions.login(page, website_url, username, password)

        # Navigate to Banking -> Process Bank Records
        functions.navigatePage(page, "Process Bank Records")

        # Cash Account Auto-Match
        # Wait until iframe is ready
        page.wait_for_selector("iframe[name='main']")
        frame = functions.wait_for_iframe(page)
        # click the last occurrence of the account name link
        accountName_link = frame.get_by_role("link", name=accountName).last
        functions.highlight_and_click(page, accountName_link)
        frame = functions.wait_for_iframe(page)
        automatch_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_AutoMatch").get_by_text("Auto-Match")
        functions.highlight_and_click(page, automatch_button)
        frame = functions.wait_for_iframe(page)
        page.wait_for_timeout(2000)  # wait 2 seconds
        abort_message = frame.get_by_text("Executing. Press to abort")
        functions.highlight(page, abort_message)
        abort_message.wait_for(state="detached", timeout=180000)
        # //*[@id="ctl00_phDS_ds_LongRun"]/span[1]

        # Wait for the completion message to appear
        success_msg = frame.locator("span.qp-lr-message")
        expect(success_msg).to_have_text("The operation has completed.", timeout=180000)
        functions.highlight(page, success_msg)

        process_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_ProcessMatched").get_by_text("Process")
        functions.highlight_and_click(page, process_button)
        page.wait_for_timeout(5000)  # wait 5 seconds
        back_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_CancelCloseToList div").nth(3)
        functions.highlight_and_click(page, back_button)
        page.wait_for_timeout(3000)  # wait 3 seconds
        
        # Wait until iframe is ready
        page.wait_for_selector("iframe[name='main']")
        frame = functions.wait_for_iframe(page)

        accountName_link = frame.get_by_role("link", name=accountName).last
        functions.highlight_and_click(page, accountName_link)
        page.wait_for_timeout(5000)  # wait 5 seconds

        # ---------------------
        # --- Main table handling with pagination ---
        has_next = True
        while has_next:
            # Wait for the grid container (not rows individually)
            frame.wait_for_selector("#ctl00_phG_PXSplitContainer_grid1_dataT0", state="attached", timeout=20000)

            # Grab all rows immediately
            table = frame.locator("#ctl00_phG_PXSplitContainer_grid1_dataT0")
            rows = table.locator("tbody tr")
            row_count = rows.count()
            functions.log_message(webhook_url, f"Found {len(rows)} rows (including phantom)")

            # Process all rows except the last phantom one
            for i, row in enumerate(rows[:-1]):
                cols = row.query_selector_all("td")
                if not cols or len(cols) < 5:
                    functions.log_message(webhook_url, f"Row {i} skipped (not enough columns)")
                    continue

                # Extract Ext. Ref. Nbr. (5th column)
                ext_ref = cols[4].inner_text().strip()
                if not ext_ref or ext_ref == "Ext. Ref. Nbr.":
                    functions.log_message(webhook_url, f"Row {i} skipped (header/empty)")
                    continue

                functions.log_message(webhook_url, f"Row {i} Ext. Ref. Nbr.: {ext_ref}")

                # First column check for icons
                first_col = cols[0]
                icon_count = len(first_col.query_selector_all("div"))

                if icon_count == 0:
                    # Unmatched row → click Ext. Ref. Nbr.
                    functions.log_message(webhook_url, f"Row {i} unmatched → clicking Ext. Ref. Nbr.")
                    try:
                        functions.highlight_and_click(page, cols[4])
                    except:
                        # Fallback: JS click if normal click fails
                        try:
                            frame.evaluate("(el) => el.click()", cols[4])
                        except:
                            cols[4].press("Enter")
                    page.wait_for_timeout(2000)
                    handle_detail_table(page, frame, webhook_url)
                else:
                    functions.log_message(webhook_url, f"Row {i} matched → skipping")

            # --- Pagination handling ---
            enabled_next = frame.locator(
                "li:nth-child(4) > .toolsBtn > .toolBtnNormal .main-icon-img.main-PageNext"
            )
            if enabled_next.count() > 0:
                functions.log_message(webhook_url, "Next button is enabled → going to next page")
                functions.highlight_and_click(page, enabled_next)
                page.wait_for_timeout(2000)
                has_next = True
            else:
                functions.log_message(webhook_url, "Next button is disabled → stopping")
                has_next = False

        # ---------------------
        # After processing all pages    
        # process_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_ProcessMatched").get_by_text("Process")
        # functions.highlight_and_click(page, process_button)
        # page.wait_for_timeout(5000)  # wait 5 seconds
        back_button = page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_CancelCloseToList div").nth(3)
        functions.highlight_and_click(page, back_button)
        page.wait_for_timeout(3000)  # wait 3 seconds
        accountName_link = frame.get_by_role("link", name=accountName).last
        functions.highlight_and_click(page, accountName_link)

        dropdown_button = page.locator("iframe[name=\"main\"]").content_frame.locator("li:nth-child(14) > .toolsBtn > .toolBtnNormal")
        functions.highlight_and_click(page, dropdown_button)
        with page.expect_download() as download_info:
            download_button = frame.locator("#ctl00_phG_PXSplitContainer_grid1_at_tlb_menuhi_item_3")
            functions.highlight_and_click(page, download_button)

        # Access the downloaded file
        download = download_info.value
        functions.log_message(webhook_url, "✅ Download started:", download.suggested_filename)

        # Save to a specific location 
        save_path = save_path + download.suggested_filename
        download.save_as(save_path)

        # Call function with the saved path (not the download object)
        output_file = process_bank_transactions(
            process_file=save_path,  
            output_file=CAMatchOutputFile,
            allowed_types=allowed_types
        )

        functions.log_message(webhook_url, f"✅ Bank Charges List created: {output_file}")
        context.close()
        browser.close()
        functions.send_pingback(pingback_url, "completed", requests = requests, payload = payload)
        # Load the Excel file and return as list of dicts
        df = pd.read_excel(output_file)

        # --- Cleaning section ---
        # Convert datetime columns (if they exist)
        for col in df.select_dtypes(include=["datetime64[ns]"]).columns:
            df[col] = df[col].dt.strftime("%d/%m/%Y")

        # Replace infinities and NaNs with empty string
        df = df.replace([float("inf"), float("-inf")], None)
        df = df.fillna("")

        # Convert everything to string
        df = df.astype(str)

        # Example: if you specifically need branch codes or IDs to preserve leading zeros:
        if "Bank Reference Number" in df.columns:
            df["Bank Reference Number"] = df["Bank Reference Number"].str.zfill(2)

        # --- End cleaning section ---

        records = df.to_dict(orient="records")

        return records
    except Exception as e:
        functions.send_pingback(pingback_url, requests, "failed", payload, str(e))
        raise

if __name__ == "__main__":
    import config
    with sync_playwright() as playwright:
        CAMatchExtract(
        playwright, 
        config.website_url,
        config.username,
        config.password,
        config.accountName, 
        config.save_path,
        config.CAMatchOutputFile,
        config.allowed_types,
        pingback_url=None,
        payload=None,
        webhook_url=None
        )
