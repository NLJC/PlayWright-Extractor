"""
Test script for the complete main RPA flow
Mimics the entire MatchStatement process from start to finish
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import pandas as pd

# Load environment variables
load_dotenv("env 1")

def test_main_flow():
    """Test the complete main RPA flow"""

    # Configuration
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    account_name = os.getenv("accountName", "CIM02")

    # Test data - Create sample data for each match type
    # Modify these with actual test data from your matching results
    test_1to1_data = {
        "Bank Reference Number": ["TEST001"],
        "CSGP Reference": ["REF001"],
    }

    test_group_data = {
        "Bank Reference Number": ["TEST002"],
        "CSGP Reference": ["REF002,REF003"],  # Multiple CSGP refs
        "reverse_ce_gl": [False]  # Regular group match
    }

    test_reverse_cegl_data = {
        "Bank Reference Number": ["TEST003", "TEST003"],
        "CSGP Reference": ["11092025", "11092025"],  # Same ref for reverse CE/GL
        "reverse_ce_gl": [True, True]
    }

    print("="*60)
    print("TESTING COMPLETE MAIN RPA FLOW")
    print("="*60)
    print(f"Account: {account_name}")
    print(f"Website: {website_url}")
    print("="*60)

    with sync_playwright() as playwright:
        from playwright_scripts.MatchStatement_Optimized import MatchStatementProcessor
        from helper_playwright import functions

        # Create processor instance
        processor = MatchStatementProcessor(
            playwright=playwright,
            match_result_path="dummy.xlsx",
            account_name=account_name,
            website_url=website_url,
            username=username,
            password=password,
            headless=False
        )

        try:
            # STEP 1: Initialize Browser
            print("\n" + "="*60)
            print("STEP 1: Initializing browser...")
            print("="*60)
            processor.initialize_browser()
            print("[OK] Browser initialized\n")

            # STEP 2: Login
            print("="*60)
            print("STEP 2: Logging in...")
            print("="*60)
            functions.login(processor.page, website_url, username, password)
            processor.frame = processor.wait_for_iframe()
            print("[OK] Login successful\n")

            # STEP 3: Load Match Results (simulated with test data)
            print("="*60)
            print("STEP 3: Loading match results...")
            print("="*60)

            dfs = {}

            if len(test_1to1_data["Bank Reference Number"]) > 0:
                dfs["1to1 Matches"] = pd.DataFrame(test_1to1_data)
                print(f"[OK] Loaded {len(dfs['1to1 Matches'])} 1-to-1 matches")

            if len(test_group_data["Bank Reference Number"]) > 0:
                group_df = pd.DataFrame(test_group_data)
                dfs["Group Match"] = group_df
                print(f"[OK] Loaded {len(dfs['Group Match'])} group matches")

            if len(test_reverse_cegl_data["Bank Reference Number"]) > 0:
                # Add reverse CE/GL data to Group Match sheet
                reverse_df = pd.DataFrame(test_reverse_cegl_data)
                if "Group Match" in dfs:
                    dfs["Group Match"] = pd.concat([dfs["Group Match"], reverse_df], ignore_index=True)
                else:
                    dfs["Group Match"] = reverse_df
                print(f"[OK] Loaded {len(test_reverse_cegl_data['Bank Reference Number'])} reverse CE/GL matches")

            print()

            # STEP 4: Process Reverse CE/GL Matches FIRST
            print("="*60)
            print("STEP 4: Processing Reverse CE/GL Matches (FIRST)")
            print("="*60)

            if "Group Match" in dfs:
                # Filter for reverse_ce_gl = True
                group_df = dfs["Group Match"]
                if "reverse_ce_gl" in group_df.columns:
                    reverse_df = group_df[group_df["reverse_ce_gl"] == True]
                    if len(reverse_df) > 0:
                        print(f"Processing {len(reverse_df)} reverse CE/GL matches...")
                        processor.process_reverse_ce_gl_matches(dfs["Group Match"])
                        print("[OK] Reverse CE/GL matches completed\n")
                    else:
                        print("No reverse CE/GL matches found, skipping\n")
                else:
                    print("No reverse_ce_gl column found, skipping\n")
            else:
                print("No Group Match data, skipping\n")

            # STEP 5: Navigate to Process Bank Records
            print("="*60)
            print("STEP 5: Navigating to Process Bank Records...")
            print("="*60)
            functions.navigatePage(processor.page, "Process Bank Records")
            processor.frame = processor.wait_for_iframe()
            account_link = processor.frame.get_by_role("link", name=account_name).last
            processor.smart_click(account_link, f"Account link: {account_name}")
            processor.smart_wait_for_page_load()
            print("[OK] Navigation successful\n")

            # STEP 6: Process 1-to-1 Matches
            print("="*60)
            print("STEP 6: Processing 1-to-1 Matches")
            print("="*60)

            if "1to1 Matches" in dfs:
                print(f"Processing {len(dfs['1to1 Matches'])} 1-to-1 matches...")
                processor.process_1to1_matches(dfs["1to1 Matches"])
                print("[OK] 1-to-1 matches completed\n")
            else:
                print("No 1-to-1 matches found, skipping\n")

            # STEP 7: Process Group Matches (excluding reverse CE/GL)
            print("="*60)
            print("STEP 7: Processing Group Matches")
            print("="*60)

            if "Group Match" in dfs:
                # Filter out reverse_ce_gl = True (already processed in Step 4)
                group_df = dfs["Group Match"]
                if "reverse_ce_gl" in group_df.columns:
                    regular_group_df = group_df[group_df["reverse_ce_gl"] != True]
                else:
                    regular_group_df = group_df

                if len(regular_group_df) > 0:
                    print(f"Processing {len(regular_group_df)} group matches...")
                    processor.process_group_matches(regular_group_df)
                    print("[OK] Group matches completed\n")
                else:
                    print("No regular group matches found, skipping\n")
            else:
                print("No Group Match data, skipping\n")

            # STEP 8: Summary
            print("="*60)
            print("STEP 8: Test Summary")
            print("="*60)
            print(f"Failed entries: {len(processor.failed_entries)}")

            if len(processor.failed_entries) > 0:
                print("\nFailed entries:")
                for entry in processor.failed_entries:
                    print(f"  - Bank Ref: {entry.get('Bank Reference Number', 'N/A')}")
            else:
                print("[OK] All entries processed successfully!")

            print("\n" + "="*60)
            print("TEST COMPLETED!")
            print("="*60)
            print("\nPress Enter to close browser...")
            input()

        except Exception as e:
            print(f"\n[ERROR] Error during test: {e}")
            import traceback
            traceback.print_exc()
            print("\nPress Enter to close browser...")
            input()

        finally:
            processor.cleanup()


if __name__ == "__main__":
    test_main_flow()
