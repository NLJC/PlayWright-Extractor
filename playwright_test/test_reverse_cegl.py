"""
Test script for reverse CE/GL matching process
Quick debug script to test the reconciliation statement filtering
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# Load environment variables
load_dotenv("env 1")

def test_reverse_cegl_matching():
    """Test the reverse CE/GL matching process"""

    # Configuration
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    account_name = os.getenv("accountName", "CIM02")

    # Test data - you can modify these values
    test_csgp_refs = ["11092025", "C8J9EHQ9"]

    print(f"Testing with account: {account_name}")
    print(f"Test CSGP refs: {test_csgp_refs}")
    print("=" * 60)

    with sync_playwright() as playwright:
        from playwright_scripts.MatchStatement_Optimized import MatchStatementProcessor

        # Create a minimal processor instance
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

            # Navigate to Reconciliation Statements
            print("Step 3: Navigating to Reconciliation Statements...")
            success = processor.navigate_to_reconciliation_statements()

            if not success:
                print("[ERROR] Failed to navigate to Reconciliation Statements")
                return

            print("[OK] Navigation successful\n")

            # Test the full reverse CE/GL matching process
            print("\n" + "="*60)
            print("Step 4: Testing Reverse CE/GL Matching Process")
            print("="*60)

            # Test with pairs of CSGP refs (simulating the actual process)
            # In real scenario, these come from the Group Match sheet where reverse_ce_gl = TRUE
            test_pairs = [
                ["11092025", "11092025"],  # Same ref appears twice (typical reverse CE/GL pattern)
                # Add more test pairs as needed
            ]

            for pair_idx, csgp_refs in enumerate(test_pairs):
                print(f"\n{'='*60}")
                print(f"Testing Reverse CE/GL Pair {pair_idx + 1}: {csgp_refs}")
                print(f"{'='*60}")

                # Search for the first CSGP ref (they should be the same or related)
                csgp_ref = csgp_refs[0]

                print(f"\nStep 4.1: Searching for Document Ref: {csgp_ref}")
                matching_records = processor.search_document_ref_in_reconciliation(csgp_ref)

                if matching_records:
                    print(f"[OK] Found {len(matching_records)} matching records")
                    for i, record in enumerate(matching_records):
                        print(f"  Record {i+1}: Description='{record.get('description', 'N/A')}'")

                    # Now test the reconciliation logic
                    print(f"\nStep 4.2: Validating and reconciling records...")
                    success = processor.validate_and_reconcile_reverse_ce_gl(matching_records, csgp_refs)

                    if success:
                        print(f"[OK] Successfully reconciled reverse CE/GL for {csgp_refs}")
                    else:
                        print(f"[ERROR] Failed to reconcile reverse CE/GL for {csgp_refs}")

                else:
                    print(f"[ERROR] No matching records found for {csgp_ref}")

                # Wait between pairs
                processor.page.wait_for_timeout(3000)

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
    test_reverse_cegl_matching()
