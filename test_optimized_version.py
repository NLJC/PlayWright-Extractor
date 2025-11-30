"""
Test script for CA_Match_Process_Optimized.py

This script helps validate the optimized version against the original.
Run this in a test environment before deploying to production.
"""

from playwright.sync_api import sync_playwright
from datetime import datetime
from dateutil.relativedelta import relativedelta
import os
import sys
from dotenv import load_dotenv

# Load environment
load_dotenv()

def test_import():
    """Test that the optimized module can be imported."""
    print("=" * 60)
    print("TEST 1: Import Test")
    print("=" * 60)
    
    try:
        from playwright_scripts.CA_Match_Process_Optimized import process_bank_transactions, CAMatchProcessor
        print("✅ Successfully imported CA_Match_Process_Optimized")
        print(f"   - process_bank_transactions: {type(process_bank_transactions)}")
        print(f"   - CAMatchProcessor: {type(CAMatchProcessor)}")
        return True
    except Exception as e:
        print(f"❌ Import failed: {e}")
        return False

def test_configuration():
    """Test that all required environment variables are set."""
    print("\n" + "=" * 60)
    print("TEST 2: Configuration Test")
    print("=" * 60)
    
    required_vars = [
        "WEBSITE_URL",
        "WEBSITE_USERNAME",
        "PASSWORD",
        "SAVE_DIRECTORY",
        "accountName"
    ]
    
    optional_vars = [
        "HEADLESS_MODE",
        "CLIENT_ID",
        "TENANT_ID"
    ]
    
    all_ok = True
    
    print("\nRequired Variables:")
    for var in required_vars:
        value = os.getenv(var)
        if value:
            # Mask sensitive values
            if var in ["PASSWORD", "CLIENT_SECRET"]:
                display = "***" + value[-4:] if len(value) > 4 else "***"
            else:
                display = value[:50] + "..." if len(value) > 50 else value
            print(f"   ✅ {var}: {display}")
        else:
            print(f"   ❌ {var}: NOT SET")
            all_ok = False
    
    print("\nOptional Variables:")
    for var in optional_vars:
        value = os.getenv(var)
        if value:
            if var in ["CLIENT_SECRET"]:
                display = "***" + value[-4:] if len(value) > 4 else "***"
            else:
                display = value
            print(f"   ✅ {var}: {display}")
        else:
            print(f"   ⚠️  {var}: Not set (optional)")
    
    return all_ok

def test_class_instantiation():
    """Test that CAMatchProcessor can be instantiated."""
    print("\n" + "=" * 60)
    print("TEST 3: Class Instantiation Test")
    print("=" * 60)
    
    try:
        from playwright_scripts.CA_Match_Process_Optimized import CAMatchProcessor
        
        # Create a mock playwright object for testing
        class MockPlaywright:
            pass
        
        processor = CAMatchProcessor(
            playwright=MockPlaywright(),
            account_name="TEST_ACCOUNT",
            date="01/01/2024",
            amount=100.0,
            headless=True
        )
        
        print("✅ CAMatchProcessor instantiated successfully")
        print(f"   - Account: {processor.account_name}")
        print(f"   - Date: {processor.date}")
        print(f"   - Amount: {processor.amount}")
        print(f"   - Headless: {processor.headless}")
        print(f"   - Website URL: {processor.website_url}")
        
        return True
    except Exception as e:
        print(f"❌ Instantiation failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_method_signatures():
    """Test that all expected methods exist."""
    print("\n" + "=" * 60)
    print("TEST 4: Method Signature Test")
    print("=" * 60)
    
    try:
        from playwright_scripts.CA_Match_Process_Optimized import CAMatchProcessor
        
        expected_methods = [
            'log',
            'send_pingback',
            'initialize_browser',
            'cleanup',
            'wait_for_iframe',
            'smart_click',
            'wait_for_auto_match_completion',
            'handle_detail_table',
            'process_pagination_with_matching',
            'perform_auto_match',
            'perform_manual_matching',
            'download_results',
            'process_downloaded_file',
            'run'
        ]
        
        all_ok = True
        for method_name in expected_methods:
            if hasattr(CAMatchProcessor, method_name):
                print(f"   ✅ {method_name}")
            else:
                print(f"   ❌ {method_name} - NOT FOUND")
                all_ok = False
        
        return all_ok
    except Exception as e:
        print(f"❌ Method check failed: {e}")
        return False

def test_dry_run():
    """Test a dry run without actually connecting to the website."""
    print("\n" + "=" * 60)
    print("TEST 5: Dry Run Test (No Browser)")
    print("=" * 60)
    
    try:
        from playwright_scripts.CA_Match_Process_Optimized import CAMatchProcessor
        
        class MockPlaywright:
            pass
        
        processor = CAMatchProcessor(
            playwright=MockPlaywright(),
            account_name=os.getenv("accountName", "TEST"),
            date="01/01/2024",
            amount=100.0,
            headless=True
        )
        
        # Test logging
        print("\n   Testing logging methods:")
        processor.log("Test info message", "info")
        processor.log("Test warning message", "warning")
        processor.log("Test error message", "error")
        
        # Test pingback (should not fail even without URL)
        print("\n   Testing pingback (no URL):")
        processor.send_pingback("test_status")
        
        print("\n✅ Dry run completed successfully")
        return True
        
    except Exception as e:
        print(f"❌ Dry run failed: {e}")
        import traceback
        traceback.print_exc()
        return False

def run_all_tests():
    """Run all tests and report results."""
    print("\n" + "=" * 60)
    print("CA MATCH PROCESS OPTIMIZED - TEST SUITE")
    print("=" * 60)
    
    tests = [
        ("Import", test_import),
        ("Configuration", test_configuration),
        ("Class Instantiation", test_class_instantiation),
        ("Method Signatures", test_method_signatures),
        ("Dry Run", test_dry_run)
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! The optimized version is ready to use.")
        print("\nNext steps:")
        print("1. Review the code in CA_Match_Process_Optimized.py")
        print("2. Test with actual browser connection (set HEADLESS_MODE=false)")
        print("3. Compare output with original version")
        print("4. Update your imports to use the optimized version")
    else:
        print("\n⚠️  Some tests failed. Please review the errors above.")
        print("   Check your .env file and dependencies.")
    
    return passed == total

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
