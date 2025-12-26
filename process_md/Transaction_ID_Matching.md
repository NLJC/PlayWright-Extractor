Transaction ID Matching
=======================

Overview
--------
Matches a bank row to a company row when the bank transaction ID appears
in the company description and amounts/dates align.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_transaction_id_matches)

Algorithm summary
-----------------
1) For each unmatched bank row:
   - Extract `Ext. Tran. ID`
   - Require valid date and net amount
2) Search company rows where:
   - Description contains the transaction ID
   - Date is within tolerance
   - Net amount within tolerance
3) Enforce transaction type match
4) Apply group-reservation guards to avoid breaking better group matches

Output
------
- `Match Type`: `transaction_id`
- 1-to-1 match (bank row -> company row)
