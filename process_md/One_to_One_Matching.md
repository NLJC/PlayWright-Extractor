1-to-1 Matching
===============

Overview
--------
1-to-1 matching applies simple one bank row to one company row matches
based on the "1to1 Matches" sheet in the RAAS+ output Excel.

Key files
---------
- `Raas_Plus/unified_reconciliation.py`
- `playwright_scripts/MatchStatement_Optimized.py`

How 1-to-1 matches are produced (RAAS+)
---------------------------------------
- The unified engine emits 1-to-1 matches into the "1to1 Matches" sheet.
- Each row maps a single bank transaction to a single company reference.

How 1-to-1 matches are applied (Playwright)
-------------------------------------------
- `process_1to1_matches(...)` reads the "1to1 Matches" sheet.
- For each row:
  1) Ensure "Match to Payments" tab is active
  2) Search for the CSGP reference in the UI
  3) Click "Match" on the first matching row

Typical failure cases
---------------------
- CSGP reference not found in UI
- UI not on correct tab
- Match button not available

Outputs
-------
- Successful matches applied in UI
- Failed rows added to `failed_entries.xlsx`
