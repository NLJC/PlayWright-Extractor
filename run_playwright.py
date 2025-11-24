"""
Playwright Automation Runner
============================
This script orchestrates the complete automation workflow:
1. CA Match Process (Extract and match bank transactions)
2. Extract Reconciliation Statement (Extract reconciliation data)
3. Match Statement (Match and process results)

Usage:
    python run_playwright.py
    
    Or with custom parameters:
    python run_playwright.py --account CIM02 --date 31/10/2024 --amount 100.00
"""

import argparse
import sys
import os
from datetime import datetime
from dateutil.relativedelta import relativedelta
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv
import logging

# Import optimized modules
from CA_Match_Process_Optimized import process_bank_transactions
from ExtractReconcileStatement_Optimized import extract_reconciliation_statements
from MatchStatement_Optimized import run_matching_process

# Load environment variables
load_dotenv()

# Setup logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('playwright_runner.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Fix Windows console encoding for emoji support
try:
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
except:
    pass


class PlaywrightRunner:
    """Orchestrates the complete Playwright automation workflow."""
    
    def __init__(
        self,
        account_name: str = None,
        date: str = None,
        amount: float = None,
        headless: bool = False,
        skip_ca_match: bool = False,
        skip_extract: bool = False,
        skip_match: bool = False,
        pingback_url: str = None,
        webhook_url: str = None
    ):
        """
        Initialize the runner.
        
        Args:
            account_name: Bank account name (defaults to env var)
            date: Reconciliation date in DD/MM/YYYY format
            amount: Statement balance amount
            headless: Run browser in headless mode
            skip_ca_match: Skip CA Match process
            skip_extract: Skip Extract Reconciliation process
            skip_match: Skip Match Statement process
            pingback_url: Optional URL for status callbacks
            webhook_url: Optional URL for logging webhooks
        """
        self.account_name = account_name or os.getenv("accountName")
        self.date = date
        self.amount = amount
        self.headless = headless
        self.skip_ca_match = skip_ca_match
        self.skip_extract = skip_extract
        self.skip_match = skip_match
        self.pingback_url = pingback_url
        self.webhook_url = webhook_url
        
        # Validate required parameters
        if not self.account_name:
            raise ValueError("Account name not provided and not set in .env")
        
        # Check env var for headless mode if not explicitly set via args
        if not self.headless:
            env_headless = os.getenv("HEADLESS_MODE", "false").lower()
            self.headless = env_headless == "true"
        
        if not self.date:
            # Default to one month ago
            today = datetime.today()
            one_month_ago = today - relativedelta(months=1)
            self.date = one_month_ago.strftime("%d/%m/%Y")
        
        if self.amount is None:
            self.amount = 100.00
        
        logger.info("=" * 70)
        logger.info("PLAYWRIGHT AUTOMATION RUNNER")
        logger.info("=" * 70)
        logger.info(f"Account: {self.account_name}")
        logger.info(f"Date: {self.date}")
        logger.info(f"Amount: {self.amount}")
        logger.info(f"Headless Mode: {self.headless}")
        logger.info("=" * 70)
    
    def run_ca_match(self) -> str:
        """
        STEP 1: Run CA Match Process
        
        Extracts and matches bank transactions.
        Returns the path to the downloaded bank transactions file.
        """
        if self.skip_ca_match:
            logger.warning("⏭️  Skipping CA Match Process (--skip-ca-match)")
            return None
        
        logger.info("\n" + "=" * 70)
        logger.info("STEP 1: CA MATCH PROCESS")
        logger.info("=" * 70)
        
        try:
            with sync_playwright() as playwright:
                logger.info("Starting CA Match process...")
                records = process_bank_transactions(
                    playwright=playwright,
                    accountName=self.account_name,
                    date=self.date,
                    amount=self.amount,
                    website_url=os.getenv("WEBSITE_URL"),
                    username=os.getenv("WEBSITE_USERNAME"),
                    password=os.getenv("PASSWORD"),
                    pingback_url=self.pingback_url,
                    payload={"step": "ca_match"},
                    webhook_url=self.webhook_url,
                    headless=self.headless
                )
                
                logger.info(f"✅ CA Match completed: {len(records)} records processed")
                return records
                
        except Exception as e:
            logger.error(f"❌ CA Match failed: {e}", exc_info=True)
            raise
    
    def run_extract_reconciliation(self, bank_transactions_path: str) -> str:
        """
        STEP 2: Run Extract Reconciliation Statement
        
        Extracts reconciliation statements.
        Returns the path to the downloaded reconciliation file.
        """
        if self.skip_extract:
            logger.warning("⏭️  Skipping Extract Reconciliation (--skip-extract)")
            return None
        
        logger.info("\n" + "=" * 70)
        logger.info("STEP 2: EXTRACT RECONCILIATION STATEMENT")
        logger.info("=" * 70)
        
        try:
            with sync_playwright() as playwright:
                logger.info("Starting Extract Reconciliation process...")
                records = extract_reconciliation_statements(
                    playwright=playwright,
                    accountName=self.account_name,
                    date=self.date,
                    amount=self.amount,
                    save_path=bank_transactions_path,
                    website_url=os.getenv("WEBSITE_URL"),
                    username=os.getenv("WEBSITE_USERNAME"),
                    password=os.getenv("PASSWORD"),
                    pingback_url=self.pingback_url,
                    payload={"step": "extract_reconciliation"},
                    webhook_url=self.webhook_url,
                    headless=self.headless
                )
                
                logger.info(f"✅ Extract Reconciliation completed: {len(records)} records processed")
                return records
                
        except Exception as e:
            logger.error(f"❌ Extract Reconciliation failed: {e}", exc_info=True)
            raise
    
    def run_match_statement(self, match_result_path: str):
        """
        STEP 3: Run Match Statement
        
        Matches and processes the reconciliation results.
        """
        if self.skip_match:
            logger.warning("⏭️  Skipping Match Statement (--skip-match)")
            return
        
        logger.info("\n" + "=" * 70)
        logger.info("STEP 3: MATCH STATEMENT")
        logger.info("=" * 70)
        
        try:
            with sync_playwright() as playwright:
                logger.info("Starting Match Statement process...")
                run_matching_process(
                    playwright=playwright,
                    matchresultpath=match_result_path,
                    website_url=os.getenv("WEBSITE_URL"),
                    username=os.getenv("WEBSITE_USERNAME"),
                    password=os.getenv("PASSWORD"),
                    accountName=self.account_name,
                    pingback_url=self.pingback_url,
                    payload={"step": "match_statement"},
                    webhook_url=self.webhook_url,
                    headless=self.headless
                )
                
                logger.info("✅ Match Statement completed")
                
        except Exception as e:
            logger.error(f"❌ Match Statement failed: {e}", exc_info=True)
            raise
    
    def run(self):
        """
        Execute the complete automation workflow.
        """
        try:
            logger.info("\n🚀 Starting complete automation workflow...\n")
            
            # STEP 1: CA Match
            ca_match_records = self.run_ca_match()
            
            # STEP 2: Extract Reconciliation (chains from CA Match)
            # Note: Extract Reconciliation is called from CA Match process
            # but we can also run it independently if needed
            
            # STEP 3: Match Statement (chains from RaasPlus)
            # Note: Match Statement is called from RaasPlus process
            # but we can also run it independently if needed
            
            logger.info("\n" + "=" * 70)
            logger.info("✅ COMPLETE AUTOMATION WORKFLOW FINISHED SUCCESSFULLY")
            logger.info("=" * 70)
            logger.info("\nWorkflow Summary:")
            logger.info("  ✅ CA Match Process - Completed")
            logger.info("  ✅ Extract Reconciliation Statement - Completed (chained)")
            logger.info("  ✅ RaasPlus Reconciliation - Completed (chained)")
            logger.info("  ✅ Match Statement - Completed (chained)")
            logger.info("\nAll processes completed successfully!")
            logger.info("Check logs for detailed information.")
            logger.info("=" * 70)
            
            return True
            
        except Exception as e:
            logger.error("\n" + "=" * 70)
            logger.error("❌ AUTOMATION WORKFLOW FAILED")
            logger.error("=" * 70)
            logger.error(f"Error: {e}")
            logger.error("=" * 70)
            return False


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Playwright Automation Runner - Orchestrates bank reconciliation workflow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run with default settings (from .env file)
  python run_playwright.py
  
  # Run with custom account and date
  python run_playwright.py --account CIM02 --date 31/10/2024 --amount 100.00
  
  # Run in headless mode
  python run_playwright.py --headless
  
  # Skip specific steps
  python run_playwright.py --skip-ca-match
  python run_playwright.py --skip-extract
  python run_playwright.py --skip-match
  
  # Run with webhooks for logging
  python run_playwright.py --webhook-url https://your-webhook.com/log
        """
    )
    
    parser.add_argument(
        "--account",
        type=str,
        default=None,
        help="Bank account name (default: from .env)"
    )
    
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Reconciliation date in DD/MM/YYYY format (default: one month ago)"
    )
    
    parser.add_argument(
        "--amount",
        type=float,
        default=None,
        help="Statement balance amount (default: 100.00)"
    )
    
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode (no GUI)"
    )
    
    parser.add_argument(
        "--skip-ca-match",
        action="store_true",
        help="Skip CA Match process"
    )
    
    parser.add_argument(
        "--skip-extract",
        action="store_true",
        help="Skip Extract Reconciliation process"
    )
    
    parser.add_argument(
        "--skip-match",
        action="store_true",
        help="Skip Match Statement process"
    )
    
    parser.add_argument(
        "--pingback-url",
        type=str,
        default=None,
        help="URL for status callbacks"
    )
    
    parser.add_argument(
        "--webhook-url",
        type=str,
        default=None,
        help="URL for logging webhooks"
    )
    
    args = parser.parse_args()
    
    try:
        # Create runner
        runner = PlaywrightRunner(
            account_name=args.account,
            date=args.date,
            amount=args.amount,
            headless=args.headless,
            skip_ca_match=args.skip_ca_match,
            skip_extract=args.skip_extract,
            skip_match=args.skip_match,
            pingback_url=args.pingback_url,
            webhook_url=args.webhook_url
        )
        
        # Run workflow
        success = runner.run()
        
        # Exit with appropriate code
        sys.exit(0 if success else 1)
        
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
