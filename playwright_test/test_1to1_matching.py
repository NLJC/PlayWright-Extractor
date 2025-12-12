"""
Test script for 1-to-1 matching process
Quick debug script to test individual 1-to-1 matches
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import pandas as pd

# Load environment variables
load_dotenv("env 1")

def test_1to1_matching():
    """Test the 1-to-1 matching process"""

    # Configuration
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    account_name = os.getenv("accountName", "CIM02")

    # Test data - modify these values to test specific matches
    test_data = {
        "Bank Reference Number": ["12345"],  # Replace with actual bank ref
        "CSGP Reference": ["67890"],  # Replace with actual CSGP ref
    }

    print(f"Testing 1-to-1 matching with account: {account_name}")
    print(f"Test data: {test_data}")
    print("=" * 60)

    with sync_playwright() as playwright:
        from playwright_scripts.MatchStatement_Optimized import MatchStatementProcessor

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
            # Initialize browser
            print("Step 1: Initializing browser...")
            processor.initialize_browser()

            # Login
            print("Step 2: Logging in...")
            from helper_playwright import functions
            functions.login(processor.page, website_url, username, password)
            print("[OK] Login successful\n")

            # Navigate to Process Bank Records
            print("Step 3: Navigating to Process Bank Records...")
            functions.navigatePage(processor.page, "Process Bank Records")
            processor.frame = processor.wait_for_iframe()
            account_link = processor.frame.get_by_role("link", name=account_name).last
            processor.smart_click(account_link, f"Account link: {account_name}")
            processor.smart_wait_for_page_load()
            print("[OK] Navigation successful\n")

            # Create test DataFrame
            df = pd.DataFrame(test_data)

            # Process 1-to-1 matches
            print("Step 4: Processing 1-to-1 matches...")
            processor.process_1to1_matches(df)

            print("\n" + "="*60)
            print("Test completed! Press Enter to close browser...")
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
    test_1to1_matching()
