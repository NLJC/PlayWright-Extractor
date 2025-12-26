Amount and Date Matching
========================

Overview
--------
Matches a bank row to a company row when the amount matches exactly
within tolerance and the date is the closest within the allowed window.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_amount_date_matches)

Algorithm summary
-----------------
1) For each unmatched bank row:
   - Require valid date and net amount
2) Find company candidates where:
   - Net amount matches within `AMOUNT_TOLERANCE`
   - Date within `DATE_TOLERANCE_DAYS`
3) Pick the candidate with smallest date difference

Output
------
- `Match Type`: `amount_date`
- 1-to-1 match (bank row -> company row)
