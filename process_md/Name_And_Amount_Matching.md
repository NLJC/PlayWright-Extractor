Name and Amount Matching
========================

Overview
--------
Matches bank and company rows using name similarity plus amount/date
alignment. This is a fuzzy-name 1-to-1 match.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_name_and_amount_matches)

Algorithm summary
-----------------
1) For each unmatched bank row:
   - Gather candidate name fields (sender/recipient/reference/desc)
2) Find company candidates within:
   - Date tolerance
   - Amount tolerance
3) Score name similarity using exact/contains/fuzzy match
4) Combine name, date, and amount scores into a weighted score
5) Apply group-reservation guards to avoid breaking better groups

Output
------
- `Match Type`: `name_and_amount`
- 1-to-1 match (bank row -> company row)
