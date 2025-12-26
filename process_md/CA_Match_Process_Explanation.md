CA Match Process Explanation
============================

Overview
--------
The CA Match step navigates the bank UI to extract bank transactions
and downloads the bank statement Excel. It is the first step in the
end-to-end workflow.

Key files
---------
- `playwright_scripts/CA_Match_Process_Optimized.py`
- `playwright_scripts/run_playwright.py` (orchestrates)

Inputs
------
- Account name (e.g., MBB02)
- Reconciliation date (DD/MM/YYYY)
- Statement balance amount
- Website URL and credentials

Outputs
-------
- Bank transactions Excel file (downloaded to the configured Downloads folder)
- In-memory records list returned to the runner

High-level flow
---------------
1) Log in to the site
2) Navigate to Cash Account match screen
3) Filter by account and date
4) Export bank transactions to Excel
5) Return the download path for chaining

How it connects to the next step
--------------------------------
The downloaded bank Excel path is passed to the Extract Reconciliation
process, which uses it as the "bank statement" reference when extracting
reconciliation statements.
