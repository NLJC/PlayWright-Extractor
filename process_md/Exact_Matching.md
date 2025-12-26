Exact Matching (Enhanced 1-to-1)
===============================

Overview
--------
Scores candidates using amount, date, reference, and description. Picks
the best match that exceeds the minimum score.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_exact_matches)

Algorithm summary
-----------------
1) For each unmatched bank row:
   - Filter company rows by txn_type and non-zero net amount
2) Score each candidate using:
   - Amount score
   - Date score
   - Reference score (exact, contains, last-6, fuzzy)
   - Description similarity
3) Select best score above `MIN_MATCH_SCORE`
4) Apply group-reservation guard

Output
------
- `Match Type`: `enhanced_1to1`
- 1-to-1 match (bank row -> company row)
