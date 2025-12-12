"""
Test script for navigation
Quick debug script to test login and navigation to different pages
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv("env 1")

def test_navigation():
    """Test navigation to various pages"""

    # Configuration
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    account_name = os.getenv("accountName", "CIM02")

    print(f"Testing navigation with account: {account_name}")
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
            print("\n1. Initializing browser...")
            processor.initialize_browser()
            print("✅ Browser initialized\n")

            # Login
            print("2. Logging in...")
            from helper_playwright import functions
            functions.login(processor.page, website_url, username, password)
            print("✅ Login successful\n")

            # Test 1: Navigate to Process Bank Records
            print("3. Testing navigation to Process Bank Records...")
            functions.navigatePage(processor.page, "Process Bank Records")
            processor.frame = processor.wait_for_iframe()
            print("✅ Successfully navigated to Process Bank Records\n")

            # Find account
            print(f"4. Looking for account: {account_name}...")
            account_link = processor.frame.get_by_role("link", name=account_name).last
            if account_link.count() > 0:
                print(f"✅ Found account link for {account_name}\n")
            else:
                print(f"❌ Could not find account link for {account_name}\n")

            input("Press Enter to test Reconciliation Statements navigation...")

            # Test 2: Navigate to Reconciliation Statements
            print("\n5. Testing navigation to Reconciliation Statements...")
            success = processor.navigate_to_reconciliation_statements()
            if success:
                print("✅ Successfully navigated to Reconciliation Statements\n")
            else:
                print("❌ Failed to navigate to Reconciliation Statements\n")

            print("\n" + "="*60)
            print("Navigation test completed! Press Enter to close browser...")
            input()

        except Exception as e:
            print(f"\n❌ Error during test: {e}")
            import traceback
            traceback.print_exc()
            print("\nPress Enter to close browser...")
            input()

        finally:
            processor.cleanup()


if __name__ == "__main__":
    test_navigation()
