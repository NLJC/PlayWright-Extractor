import logging
from pathlib import Path
from typing import Optional

import pandas as pd

# Setup a logger for this module
logger = logging.getLogger("AttachmentUtils")

def identify_file_type(file_path: Path) -> str:
    """
    Analyze the file content to determine its type.
    
    Returns:
        "DAILY_REPORT" - If it matches JomPAY/Daily Report structure.
        "CREDIT_CARD" - If it matches Credit Card transaction structure.
        "UNKNOWN" - If it doesn't match known types.
    """
    if not file_path.exists():
        logger.error(f"File not found: {file_path}")
        return "UNKNOWN"

    # Only process Excel or CSV
    suffix = file_path.suffix.lower()
    if suffix not in [".xlsx", ".xls", ".csv"]:
        return "UNKNOWN"

    try:
        # Read the first few rows to inspect headers/content
        if suffix == ".csv":
            # Read first 20 lines to cover potential headers
            df = pd.read_csv(file_path, nrows=20, header=None)
        else:
            # Read first 20 rows of the first sheet
            df = pd.read_excel(file_path, nrows=20, header=None)

        # Convert entire dataframe to string for easier searching
        df_str = df.astype(str).apply(lambda x: x.str.upper())

        # Check for JomPAY / Daily Report markers
        # Key markers based on phase1_process_jompay_reports.py and user context
        jompay_markers = ["JOMPAY", "BILLER CODE", "JOMPAY REF NO", "PAYER BANK NAME"]
        
        # Check if ANY of the markers exist in the dataframe
        is_jompay = False
        for col in df_str.columns:
            col_values = df_str[col].tolist()
            if any(any(marker in str(val) for marker in jompay_markers) for val in col_values):
                is_jompay = True
                break
        
        if is_jompay:
            return "DAILY_REPORT"

        # Check for Credit Card markers
        # Based on user info: "Settlement", or cell C14/B4 having specific data
        # We look for "MERCHANT" or "SETTLEMENT" or "CARD NO" or "TID"
        cc_markers = ["MERCHANT ID", "SETTLEMENT DATE", "CARD NUMBER", "TERMINAL ID", "MID", "TID"]
        
        is_cc = False
        for col in df_str.columns:
            col_values = df_str[col].tolist()
            if any(any(marker in str(val) for marker in cc_markers) for val in col_values):
                is_cc = True
                break
        
        if is_cc:
            return "CREDIT_CARD"

    except Exception as e:
        logger.warning(f"Failed to analyze file {file_path.name}: {e}")

    return "UNKNOWN"
