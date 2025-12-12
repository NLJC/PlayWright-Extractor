"""
Test script for group matching process (1-to-many)
Quick debug script to test group matches
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright
import pandas as pd

# Load environment variables
load_dotenv("env 1")

def test_group_matching():
    """Test the group matching process"""

    # Configuration
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    account_name = os.getenv("accountName", "CIM02")

    # Test data - modify these values to test specific group matches
    test_data = {
        "Bank Reference Number": ["12345"],  # Single bank ref
        "CSGP Reference": ["67890,67891,67892"],  # Multiple CSGP refs (comma-separated)
        "Match Type": ["group"]  # or "reverse_ce_gl" if testing that type
    }

    print(f"Testing group matching with account: {account_name}")
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

            # Process group matches
            print("Step 4: Processing group matches...")
            processor.process_group_matches(df)

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
    test_group_matching()
