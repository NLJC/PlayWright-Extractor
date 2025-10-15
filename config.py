#  login details
# website_url = "https://efmisstg.pdc.gov.my/efmis/Frames/Login.aspx?ReturnUrl=%2fefmis%2f"
# username = "cognitive"
# password = "Abcd1234"
website_url = "https://csmstg.censof.com/DBKK"
username = "rpauser"
password = "Rp@12345"

# Account details
accountName = "CIM02"

# Excel file paths
save_path = "D:/PlayWright Extractor"
CAMatchOutputFile = "Processed_Bank_Charges_List.xlsx"
matchresultpath = "unified_results_20250911_153953.xlsx"

# allowed patterns (regex, case-insensitive)
allowed_types = [
    r"^I-PAYMENT CHARG$",             # exact
    r"MISCELLANEOUS C",               # contains
    r"^OTHER TRANSFER",                # startswith
    r"^CHQ PROCESSING",                # startswith
    r"^OTHER FEE$",                    # exact
    r"^OTHER TRANSFER FEE$",           # exact
    r"^CHQ PROCESSING FEE$",           # exact
    r"^SVG CHG/OTHERS$",               # exact
    r"^STAMP DUTY - CO$",              # exact
    r"^SERVICE CHARGE$",               # exact
    r"SWIFT SETUP",                    # contains
    r"^3RD PARTY CHEQUE ENCASHMENT CHARGE$",  # exact
]

# allowed types
failed_entry_columns = [
        "Bank Statement Date", "Bank Transaction ID", "Bank Reference Number", "Bank Description",
        "Bank Receipt", "Bank Disbursement",
        "CSGP Transaction Date", "CSGP Reference", "CSGP Module", "CSGP Description",
        "CSGP Receipt", "CSGP Disbursement",
        "Amount Difference", "Date Difference", "Reason", "Confidence", "Match Type",
        "Bank_UID", "CSGP_UID"
    ]