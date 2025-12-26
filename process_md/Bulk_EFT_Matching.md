Bulk EFT Matching
=================

Overview
--------
Matches a group of bank disbursements with an EFT reference pattern
to a single company disbursement that contains the EFT number.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_bulk_eft_matches)

When it runs
------------
- `ENABLE_BULK_EFT == True`
- Bank gating default: `BANK_NAME == "MBB01"`
  - Can be overridden by `BULK_EFT_ALLOW_ANY_BANK == True`

Algorithm summary
-----------------
1) Filter unmatched bank rows with reference pattern `L<yymm><eft>`
2) Group by full reference (L+yymm+EFT)
3) Sum disbursement net amounts in each group
4) Find company rows whose reference or description contains the EFT number
5) Choose the company row with smallest amount difference

Output
------
- `Match Type`:
  - `custom_bulk_eft` (exact or within tolerance)
  - `custom_bulk_eft_with_rejects` (amount difference exists)
- Group match (bank group -> single company row)
