Custom Structured Group Matching
================================

Overview
--------
Groups bank rows with a specific description (default "AUTOPAY DR") that
share the same bank reference and date, then matches the group to a
single company row with the same date and net amount.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_custom_structured_group_matches)

When it runs
------------
- `ENABLE_CUSTOM_MATCHING == True`
- `ENABLE_CUSTOM_STRUCTURED_GROUP == True`

Algorithm summary
-----------------
1) Filter unmatched bank rows where `Tran. Desc == STRUCT_GROUP_DESC_VALUE`
2) Group by `Ext. Ref. Nbr.` and `Tran. Date`
3) Require group size >= `MIN_STRUCTURED_GROUP_SIZE`
4) Sum bank net amounts and find company rows:
   - Same `Doc. Date` (or within tolerance if configured)
   - Same txn_type
   - Net amount difference <= `AMOUNT_TOLERANCE`
5) If multiple company candidates exist, use a tie-breaker on
   description/reference similarity (optional)

Output
------
- `Match Type`: `custom_structured_group`
- Group match (bank group -> single company row)
