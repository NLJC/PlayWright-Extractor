Playwright Runner Overview
==========================

Overview
--------
The runner orchestrates the full end-to-end workflow:
CA Match -> Extract Reconcile Statement -> RaasPlus -> Match Statement.

Key files
---------
- `playwright_scripts/run_playwright.py`
- `run_playwright.py` (thin wrapper)

Execution order
---------------
1) CA Match
   - Downloads bank transactions Excel
2) Extract Reconcile Statement
   - Downloads reconciliation Excel
   - Chains to RaasPlus
3) RaasPlus
   - Converts both Excels to JSON
   - Runs reconciliation
   - Produces match-result Excel
4) Match Statement
   - Applies matches in UI based on the Excel

How to run
----------
Default:
`python run_playwright.py`

With parameters:
`python run_playwright.py --account MBB02 --date 31/10/2024 --amount 100.00`
