JomPAY CR Group Matching
========================

Overview
--------
Matches a set of company JomPAY references (from a JSON feed) to a single
bank AUTOPAY CR entry on the next day with an exact net amount match.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_jompay_cr_group_matches_from_json)

When it runs
------------
- `ENABLE_CUSTOM_MATCHING == True`
- `ENABLE_JOMPAY_CR_GROUP == True`
- JSON file exists (default `json/phase1_jompay_consolidated.json`)

Algorithm summary
-----------------
1) Load groups from JSON (`date`, `jompay_ref_nos`, `total_amount`, `total_net_amount`)
2) Company side:
   - `Document Ref.` must include all refs
   - All rows share the exact `Doc. Date`
   - Sum of `Receipt` equals JSON `total_amount`
3) Bank side:
   - `Tran. Desc == "AUTOPAY CR"`
   - `Tran. Date` is the next day after JSON `date`
   - Bank net equals JSON `total_net_amount`

Output
------
- `Match Type`: `jompay_cr_group`
- Group match (bank row -> multiple company rows)
