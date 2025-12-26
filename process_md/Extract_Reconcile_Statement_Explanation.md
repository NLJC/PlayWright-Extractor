Extract Reconcile Statement Explanation
=======================================

Overview
--------
This step extracts reconciliation statements from the UI, downloads the
reconciliation Excel, and then chains into RaasPlus automatically.

Key files
---------
- `playwright_scripts/ExtractReconcileStatement_Optimized.py`
- `playwright_scripts/RaasPlus.py`

Inputs
------
- Account name
- Reconciliation date and balance amount
- Bank transactions Excel path from CA Match

Outputs
-------
- Reconciliation statements Excel file (downloaded)
- In-memory records list
- Automatic call into RaasPlus

High-level flow
---------------
1) Navigate to reconciliation statements
2) Filter by account and date/balance
3) Export reconciliation statements to Excel
4) Save reconciliation in the UI
5) Chain into RaasPlus with:
   - `save_path` = bank Excel
   - `reconciliation_save_path` = reconciliation Excel

How it connects to RaasPlus
---------------------------
`RaasPlus.run_RaasPlus(...)` is called at the end of this step to:
- Convert both Excels to JSON
- Run the reconciliation engine
- Produce the match-result Excel for the final UI matching
