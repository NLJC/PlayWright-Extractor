import re
from playwright.sync_api import Playwright, sync_playwright, expect
import functions
import config
import pandas as pd
import datetime

def detect_date_format(series):
    """Try to infer whether the file uses dayfirst or monthfirst."""
    sample = series.dropna().astype(str).head(20)

    dayfirst_count = 0
    monthfirst_count = 0

    for value in sample:
        try:
            d, m, y = [int(x) for x in value.replace("-", "/").split("/")[:3]]
            # If the first number > 12, it must be dayfirst
            if d > 12:
                dayfirst_count += 1
            # If the second number > 12, it must be monthfirst
            elif m > 12:
                monthfirst_count += 1
        except:
            pass

    # Decide based on majority vote
    if dayfirst_count >= monthfirst_count:
        return True   # dayfirst=True
    else:
        return False  # dayfirst=False

def format_excel_date(value, dayfirst=True):
    """Format any Excel or string date into DD/MM/YYYY."""
    if pd.isna(value):
        return ""

    if isinstance(value, (int, float)):
        # Excel serial date
        base_date = pd.to_datetime("1899-12-30")
        parsed = base_date + pd.to_timedelta(int(value), unit="D")
    else:
        parsed = pd.to_datetime(str(value), errors="coerce", dayfirst=dayfirst)

    if pd.isna(parsed):
        return str(value)

    return parsed.strftime("%d/%m/%Y")

def get_account_mapping(file_path, cash_account):
    df = pd.read_excel(file_path, sheet_name="Sheet1")
    match = df[df["Cash Account"] == cash_account]

    if match.empty:
        raise ValueError(f"No matching entry found for cash account: {cash_account}")

    row = match.iloc[0]

    # Convert everything to string
    accountcode = str(row["Offset Account"])
    subaccount = str(row["Offset Subaccount"])
    branch = str(row.get("Branch", "")).zfill(3) # zero-pad to 3 digits


    return accountcode, subaccount, branch

def load_excel_to_df(file_path: str, sheet_name: str = None) -> pd.DataFrame:
    """
    Reads an Excel file into a pandas DataFrame for testing purposes.
    
    Args:
        file_path (str): Path to the Excel file.
        sheet_name (str, optional): Name of the sheet to load. If None, loads the first sheet.
    
    Returns:
        pd.DataFrame: Loaded DataFrame.
    """
    try:
        if sheet_name:
            df = pd.read_excel(file_path, sheet_name=sheet_name, engine="openpyxl")
        else:
            df = pd.read_excel(file_path, engine="openpyxl")
        print("✅ Excel loaded successfully!")
        print("📊 Preview of data:")
        print(df.head())  # show first 5 rows
        return df
    except Exception as e:
        print(f"❌ Failed to read Excel file: {e}")
        return pd.DataFrame()  # return empty DataFrame if error

def scroll_grid_to_column(frame, col_index=10):
    grid = frame.locator("#ctl00_phG_tab_t0_grid_dataT0")
    grid.evaluate(f"el => el.parentElement.scrollLeft = {col_index * 150}")  
    # 150 = rough column width, adjust if needed

def fill_grid_cell(frame, row_index=0, column_name="Amount", value="0.50"):
    # 1. Find headers
    headers = frame.locator("#ctl00_phG_tab_t0_grid_dataT0 thead tr td")
    header_count = headers.count()

    col_index = None
    for i in range(header_count):
        text = headers.nth(i).inner_text().strip()
        if text.lower() == column_name.lower():
            col_index = i
            break

    if col_index is None:
        raise Exception(f"Column '{column_name}' not found")

    # 2. Target row + cell
    row = frame.locator(
        "#ctl00_phG_tab_t0_grid_dataT0 tbody tr:not([id*='newRow'])"
    ).nth(row_index)
    cell = row.locator("td").nth(col_index)

    # 3. Enter edit mode
    cell.scroll_into_view_if_needed()
    cell.dblclick(force=True)

    # 4. Try editor inside the cell
    editor = cell.locator("input[type='text']:visible, textarea:visible")

    try:
        editor.wait_for(state="visible", timeout=1000)
    except:
        # 5. Fallback: look only inside THIS grid
        editor = frame.locator(
            "#ctl00_phG_tab_t0_grid input.editor:visible, #ctl00_phG_tab_t0_grid textarea.editor:visible"
        )
        editor.first.wait_for(state="visible", timeout=1000)

    # 6. Fill
    editor.first.type(value)

def type_and_select(frame, cashAccount: str, locator: str):
    # Fill in the textbox
    frame.locator(locator).click()
    frame.locator(locator).type(cashAccount)
    
    # Build regex pattern safely from variable
    pattern = rf"^{re.escape(cashAccount)}\b"

    # Click the first matching option from the dropdown
    frame.locator(f"text=/{pattern}/").first.click()

def get_transaction_amount(row):
    receipt = row.get("Bank Receipt", 0) or 0
    disbursement = row.get("Bank Disbursement", 0) or 0

    # Convert to float safely
    try:
        receipt = float(receipt)
    except:
        receipt = 0
    try:
        disbursement = float(disbursement)
    except:
        disbursement = 0

    # Prefer whichever is nonzero
    if disbursement != 0:
        return disbursement
    else:
        return receipt

def writeNewStatement(page, trans_date, document_ref, description, amount, accountcode, subaccount, branch, accountName, payment_type):
    frame = page.frame(name="main")

    type_and_select(frame, accountName, "#ctl00_phF_form_t0_edCashAccountID_text")
    type_and_select(frame, payment_type, "#ctl00_phF_form_t0_edEntryTypeID_text")
    page.locator("iframe[name=\"main\"]").content_frame.get_by_role("textbox", name="Document Ref.:").click()
    page.locator("iframe[name=\"main\"]").content_frame.get_by_role("textbox", name="Document Ref.:").fill(document_ref)

    # Fill Tran. Date
    date_box = frame.get_by_role("textbox", name="Tran. Date:")
    date_box.click()
    date_box.type(trans_date)  # slow typing

    page.locator("iframe[name=\"main\"]").content_frame.get_by_role("textbox", name="Description:").click()
    page.locator("iframe[name=\"main\"]").content_frame.get_by_role("textbox", name="Description:").fill(description)
    page.locator("iframe[name=\"main\"]").content_frame.locator(".main-icon-img.main-RecordAdd").first.click()
    page.locator("iframe[name=\"main\"]").content_frame.locator("[id=\"_ctl00_phG_tab_t0_grid_lv0_edBranchID_text\"]").click()

    frame = page.frame_locator("iframe[name='main']")

    # Wait for table body
    frame.locator("#ctl00_phG_tab_t0_grid_dataT0 tbody tr:not([id*='newRow'])").first.wait_for()

    # Scroll to column
    scroll_grid_to_column(frame, col_index=3)
    # Fill column
    fill_grid_cell(frame, row_index=0, column_name="Branch", value=branch) 

    # Scroll to column
    scroll_grid_to_column(frame, col_index=10)
    # Fill column
    fill_grid_cell(frame, row_index=0, column_name="Amount", value=amount) 

    # Scroll to column
    scroll_grid_to_column(frame, col_index=11)
    # Fill column
    fill_grid_cell(frame, row_index=0, column_name="Offset Account", value=accountcode)

    # Scroll to column
    scroll_grid_to_column(frame, col_index=13)
    # Fill column
    fill_grid_cell(frame, row_index=0, column_name="Offset Subaccount", value=subaccount)

    # page.reload()

    page.once("dialog", lambda dialog: dialog.dismiss())
    page.locator("iframe[name=\"main\"]").content_frame.locator("#ctl00_phDS_ds_ToolBar_SaveCloseToList div").first.click()
    page.wait_for_timeout(10000)  # wait 10 seconds

def run_add_statement(playwright: Playwright, inputFile, matchFile, accountName, payment_type) -> None:
    # open browser
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context()
    page = context.new_page()
    # Login
    functions.login(page, config.website_url, config.username, config.password)
    page.wait_for_timeout(2000)  # wait 2 seconds

    df = load_excel_to_df(inputFile, "Bank Charges")
    print(df.columns)  # check available columns

    accountcode, subaccount, branch = get_account_mapping(matchFile, accountName)
    print(accountcode)  # use separately
    print(subaccount)
    print(branch)
    for idx, row in df.iterrows():
        # Extract variables (single-use per entry)
        trans_date = format_excel_date(row.get("Bank Statement Date"))
        print(trans_date)
        document_ref_raw = row.get("Bank Reference Number", "")
        description = row.get("Bank Description", "")
        amount = get_transaction_amount(row)
        print(amount)

        # --- Skip rows with missing required fields ---
        if (
            pd.isna(trans_date) or str(trans_date).strip() == "" or
            pd.isna(document_ref_raw) or str(document_ref_raw).strip() == "" or
            pd.isna(description) or str(description).strip() == "" or
            pd.isna(amount) or str(amount).strip() == ""
        ):
            print(f"Skipping row {idx}: missing required field(s)")
            continue

        # --- Split multiple bank refs ---
        bank_refs = [ref.strip() for ref in str(document_ref_raw).split(",") if ref.strip()]

        prev_ref = None
        for document_ref in bank_refs:
            if document_ref == prev_ref:
                print(f"Skipping duplicate bank ref '{document_ref}' in row {idx}")
                continue
            prev_ref = document_ref

            functions.navigatePage(page, "New Cash Entry")
            writeNewStatement(
                page,
                trans_date,
                str(document_ref),
                str(description),
                str(amount),
                str(accountcode),
                str(subaccount),
                str(branch),
                accountName,
                payment_type
            )

    # ---------------------
    context.close()
    browser.close() 

if __name__ == "__main__":
    with sync_playwright() as playwright: 
        run_add_statement(playwright, "Cash Transactions List-MBB01 1.xlsx", "BankMapping 1.xlsx", "MBB01", "CBPAYMENT")