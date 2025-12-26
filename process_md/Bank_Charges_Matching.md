Bank Charges Matching
=====================

Overview
--------
Detects small disbursements that look like bank charges and classifies
them without a company-side match.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (find_bank_charges)

Algorithm summary
-----------------
1) For each bank row:
   - Disbursement > 0 and < 100
   - Receipt == 0
   - Description matches a charge keyword (fee/charge/etc.)
2) Create a match with `company_tx_id = "N/A"`

Output
------
- `Match Type`: `bank_charge`
- 1-sided match (bank only)
