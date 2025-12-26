Reverse CE/GL Process
=====================

Overview
--------
Reverse CE/GL matches are handled as a special-case group flow that is
processed before the normal group/1-to-1 matching in the UI.

Key files
---------
- `Raas_Plus/unified_reconciliation.py`
- `playwright_scripts/MatchStatement_Optimized.py`

How matches are produced (RAAS+)
--------------------------------
- The unified engine emits rows into the "Group Match" sheet where:
  - `Match Type` == `reverse_ce_gl`
  - `CSGP Reference` contains two references (comma-separated)
- These rows are created by the reverse CE/GL matcher in the
  reconciliation pipeline.

How matches are applied (Playwright)
------------------------------------
- `MatchStatement_Optimized.process_reverse_ce_gl_matches(...)` runs first.
- It filters the Group Match sheet for `Match Type == reverse_ce_gl`.
- Each row is processed in the Reconciliation Statements UI without
  navigating away between rows.
- The group matching step explicitly skips reverse CE/GL rows, because
  they are handled here.

Key behavior in UI
------------------
1) Navigate to Reconciliation Statements
2) For each row:
   - Split `CSGP Reference` into 2 refs
   - Validate both references are present
   - Reconcile the pair
3) If a row is invalid or fails, it is added to `failed_entries.xlsx`
