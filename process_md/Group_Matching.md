Group Matching
==============

Overview
--------
Group matching handles 1-to-many, many-to-1, and group-style matches.
It uses semantic-first grouping and then falls back to traditional
group search if needed.

Key files
---------
- `Raas_Plus/unified_reconciliation.py`
- `playwright_scripts/MatchStatement_Optimized.py`

How group matches are produced (RAAS+)
--------------------------------------
- The unified engine runs:
  1) Semantic group matching
  2) Fallback group search (one-to-many and many-to-one)
- The results are emitted into the "Group Match" sheet.
- The sheet includes:
  - Bank Reference Number
  - CSGP Reference (comma-separated list)
  - Match Type

How group matches are applied (Playwright)
------------------------------------------
- `process_group_matches(...)` reads the "Group Match" sheet.
- It skips `reverse_ce_gl` entries (handled elsewhere).
- For each row:
  1) Filter the UI table by `Ext. Ref. Nbr.` (bank reference)
  2) Enable "Multiple Matching"
  3) Search and match each CSGP reference

Typical failure cases
---------------------
- Bank reference not found in UI table
- One of the CSGP references cannot be matched
- UI table is empty after filtering

Outputs
-------
- Successful matches applied in UI
- Failed rows added to `failed_entries.xlsx`
