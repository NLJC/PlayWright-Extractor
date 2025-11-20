"""
Simple Playwright Runner
========================
Quick and easy way to run the complete automation workflow.

Usage:
    python run_simple.py
"""

import os
import sys
from datetime import datetime
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

# Import optimized modules
from CA_Match_Process_Optimized import process_bank_transactions

# Load environment variables
load_dotenv()

# Fix Windows console encoding for emoji support
try:
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
except:
    pass


def main():
    """Run the complete automation workflow."""
    
    print("\n" + "=" * 70)
    print("PLAYWRIGHT AUTOMATION - SIMPLE RUNNER")
    print("=" * 70)
    
    # Get configuration from environment
    account_name = os.getenv("accountName", "CIM02")
    website_url = os.getenv("WEBSITE_URL")
    username = os.getenv("WEBSITE_USERNAME")
    password = os.getenv("PASSWORD")
    
    # Calculate date (one month ago)
    today = datetime.today()
    one_month_ago = today - relativedelta(months=1)
    formatted_date = one_month_ago.strftime("%d/%m/%Y")
    
    print(f"\n📋 Configuration:")
    print(f"   Account: {account_name}")
    print(f"   Date: {formatted_date}")
    print(f"   Amount: 100.00")
    print(f"   Website: {website_url}")
    print("\n" + "=" * 70)
    
    try:
        # Run the complete workflow
        print("\n🚀 Starting automation workflow...\n")
        
        with sync_playwright() as playwright:
            # This will automatically chain to:
            # 1. Extract Reconciliation Statement
            # 2. RaasPlus Reconciliation
            # 3. Match Statement
            records = process_bank_transactions(
                playwright=playwright,
                accountName=account_name,
                date=formatted_date,
                amount=100.00,
                website_url=website_url,
                username=username,
                password=password,
                headless=False  # Set to True to run without GUI
            )
        
        print("\n" + "=" * 70)
        print("✅ AUTOMATION WORKFLOW COMPLETED SUCCESSFULLY")
        print("=" * 70)
        print(f"\n📊 Results:")
        print(f"   Records Processed: {len(records)}")
        print(f"   Status: Success")
        print("\n" + "=" * 70)
        
    except Exception as e:
        print("\n" + "=" * 70)
        print("❌ AUTOMATION WORKFLOW FAILED")
        print("=" * 70)
        print(f"\n❌ Error: {e}")
        print("\nPlease check the logs for more details.")
        print("=" * 70)
        raise


if __name__ == "__main__":
    main()
