
import pandas as pd
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Add root to sys.path to ensure imports work
sys.path.append(os.getcwd())

# Mock email functions to prevent sending emails
import helper_playwright.email_reply
helper_playwright.email_reply.reply_to_trigger_email = MagicMock(side_effect=lambda msg: print(f"[MOCK EMAIL] reply_to_trigger_email: {msg}"))
helper_playwright.email_reply.reply_with_attachment = MagicMock(side_effect=lambda msg, path: print(f"[MOCK EMAIL] reply_with_attachment: {msg}, Path: {path}"))

import helper_playwright.functions
from playwright_scripts.MatchStatement_Optimized import run_matching_process

# Monkeypatch login to increase timeout
def patched_login(page, website_url, username, password):
    print(f"Logging in to {website_url} with timeout=120000ms...")
    page.goto(website_url, timeout=120000)
    dropdown = page.locator("#cmbCompany")  
    dropdown.select_option("DBKK UAT")  # by value or visible text
    page.get_by_role("textbox", name="Username").click()
    page.get_by_role("textbox", name="Username").fill(username)
    page.get_by_role("textbox", name="Password").click()
    page.get_by_role("textbox", name="Password").fill(password)
    # page.get_by_role("button", name="Next").click()
    page.get_by_role("button", name="Sign In").click()

helper_playwright.functions.login = patched_login

def main():
    input_file = Path("test_dataset/MATCHLIST_MBB02_20251223_174238.xlsx")
    temp_file = Path("test_dataset/temp_MATCHLIST_TEST.xlsx")
    
    print(f"Loading {input_file}...")
    try:
        xl = pd.ExcelFile(input_file)
        print(f"Sheet names: {xl.sheet_names}")
        
        dfs = pd.read_excel(input_file, sheet_name=None) # Read all sheets
        
        # Check if 'Group Match' sheet exists
        if "Group Match" in dfs:
            df_group = dfs["Group Match"]
            print(f"Group Match sheet found with {len(df_group)} rows.")
            
            if "Match Type" in df_group.columns:
                # Count usages of reverse_ce_gl
                rev_count = df_group[df_group["Match Type"].astype(str).str.lower() == "reverse_ce_gl"].shape[0]
                print(f"Found {rev_count} rows with Match Type 'reverse_ce_gl'.")
                
                if rev_count > 0:
                    print("Modifying 'reverse_ce_gl' to 'Manual_Test_Group' to bypass special handling and force regular processing...")
                    # Update the Match Type to allow it to fall through to regular group matching logic
                    # The script skips "reverse_ce_gl", so anything else will be processed.
                    df_group.loc[df_group["Match Type"].astype(str).str.lower() == "reverse_ce_gl", "Match Type"] = "Manual_Test_Group"
                    
                    # Update the dataframe in the dictionary
                    dfs["Group Match"] = df_group
            else:
                print("Warning: 'Match Type' column not found in 'Group Match' sheet.")
        else:
            print("Error: 'Group Match' sheet not found in input file.")
            
        print(f"Saving modified data to {temp_file}...")
        with pd.ExcelWriter(temp_file) as writer:
            for sheet_name, df in dfs.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)
                
        print("Starting Matching Process...")
        
        # We need to run Playwright
        from playwright.sync_api import sync_playwright
        
        with sync_playwright() as p:
            run_matching_process(
                playwright=p,
                matchresultpath=str(temp_file),
                headless=False
            )
            
    except Exception as e:
        print(f"An error occurred: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
