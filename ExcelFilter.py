import polars as pl
import pandas as pd
import functions

def process_bank_transactions(process_file: str, output_file: str, allowed_types=None):
    """
    Convert 'Process Bank Transactions' Excel into 'Bank Charges List' format.

    Parameters:
        process_file (str): Path to the Process Bank Transactions Excel file.
        output_file (str): Path where the formatted Bank Charges List will be saved.
        allowed_types (list, optional): List of Transaction Types to keep.
                                        If None or empty, no filtering is applied.
    """

    process_df = functions.safe_read_excel(process_file)

    # Build one regex pattern (combine all with OR)
    pattern = "|".join(f"(?:{p})" for p in allowed_types)

    # Filter DataFrame
    process_df = process_df[
        process_df["Tran. Desc"].str.upper().str.contains(pattern, regex=True, na=False)
    ]

    # === Map columns from Process Bank Transactions ===
    mapped_df = pd.DataFrame()
    mapped_df["Bank Statement Date"] = pd.to_datetime(
        process_df.get("Tran. Date", "")
    ).dt.date

    # Force IDs and references to strings so negatives and leading zeros are preserved
    mapped_df["Bank Transaction ID"] = process_df.get("Ext. Tran. ID", "").astype(str)
    mapped_df["Bank Reference Number"] = process_df.get("Ext. Ref. Nbr.", "").astype(str)

    mapped_df["Bank Description"] = process_df.get("Tran. Desc", "")
    mapped_df["Bank Receipt"] = process_df.get("Receipt", "")
    mapped_df["Bank Disbursement"] = process_df.get("Disbursement", "")

    # === Map CSGRP columns if they exist, else blank ===
    mapped_df["CSGRP Transaction Date"] = process_df.get("CSGRP Tran. Date", "")
    mapped_df["CSGRP Reference"] = process_df.get("CSGRP Reference", "")
    mapped_df["CSGRP Module"] = process_df.get("CSGRP Module", "")
    mapped_df["CSGRP Receipt"] = process_df.get("CSGRP Receipt", "")
    mapped_df["CSGRP Disbursement"] = process_df.get("CSGRP Disbursement", "")

    # === Compute Total Bank Charges ===
    bank_disb = pd.to_numeric(mapped_df["Bank Disbursement"], errors="coerce").fillna(0)
    csgrp_disb = pd.to_numeric(mapped_df["CSGRP Disbursement"], errors="coerce").fillna(0)
    mapped_df["Total Bank Charges"] = bank_disb - csgrp_disb

    # === Hardcoded final column order ===
    final_columns = [
        "Bank Statement Date",
        "Bank Transaction ID",
        "Bank Reference Number",
        "Bank Description",
        "Bank Receipt",
        "Bank Disbursement",
        "CSGRP Transaction Date",
        "CSGRP Reference",
        "CSGRP Module",
        "CSGRP Receipt",
        "CSGRP Disbursement",
        "Total Bank Charges",
    ]

    # Reorder
    final_df = mapped_df[final_columns]

    # === Save to Excel ===
    final_df.to_excel(output_file, index=False)

    return output_file

# Run only if executed directly (not imported)
if __name__ == "__main__":
    # Define allowed patterns (regex, case-insensitive)
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

    process_bank_transactions("Process Bank Transactions 20250910.xlsx", "Processed_Bank_Charges_List.xlsx", allowed_types)