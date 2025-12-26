Hungarian 1-to-1 Matching
=========================

Overview
--------
Computes a global optimal set of 1-to-1 matches using the Hungarian
algorithm (or a mutual-best fallback if SciPy is unavailable).

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_hungarian_1to1_matches)

Algorithm summary
-----------------
1) Build candidate pairs for unmatched bank/company rows
2) Score each pair using amount/date/reference/description weights
3) Apply a hard amount gate to prune impossible pairs
4) Use Hungarian assignment to select optimal 1-to-1 matches
   - If SciPy is missing, fall back to mutual-best heuristic

Output
------
- `Match Type`: `hungarian_1to1`
- 1-to-1 match (bank row -> company row)
