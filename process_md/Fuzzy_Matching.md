Fuzzy Matching
==============

Overview
--------
Matches bank and company rows using fuzzy description similarity, while
enforcing amount/date constraints and transaction type matching.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_fuzzy_matches)

Algorithm summary
-----------------
1) For each unmatched bank row:
   - Filter company rows by date and amount tolerance
   - Enforce txn_type match
2) Compute description similarity (token set ratio)
3) Pick the highest-scoring candidate above `MIN_FUZZY_SCORE`
4) Apply group-reservation guard

Output
------
- `Match Type`: `fuzzy`
- 1-to-1 match (bank row -> company row)
