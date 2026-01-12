Transaction ID Matching
=======================

Overview
--------
A high-confidence matching strategy that identifies specific transaction IDs (like bank-generated unique IDs) embedded within the descriptions or references of the datasets.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_transaction_id_matches`)

Algorithm Logic
---------------
1. **ID Extraction**:
   - Extracts the `BANK_TXN_ID_FIELD` from the bank transaction (e.g., a specific portal ID or reference).
2. **Search**:
   - Searches for this exact ID string within the **Company Description** field (case-insensitive).
3. **Constraints**:
   - **Amount**: Must match within `AMOUNT_TOLERANCE`.
   - **Date**: Must fall within the `DATE_TOLERANCE_DAYS` window.
   - **Type**: Transaction types (Credit/Debit) must match.
4. **Scoring**: Automatically assigns a high base score of **95%** due to the specificity of the match.

Inputs
------
### Bank Dataset
- `Tran. ID` (Source)
- `net_amount`, `Date`

### Company Dataset
- `Description` (Search Target)
- `net_amount`, `Date`

Outputs
-------
- **Match Type**: `transaction_id`
- **Match Score**: 95.0
- **Explanation**: "Matched on transaction ID [ID] in description. Net amount: [Bank] vs [Company]".

Example
-------
**Bank Record**: ID: `TXN998877` | Amount: 750.00
**Company Record**: Desc: `Payment for inv - TXN998877` | Amount: 750.00

**Result**: High-confidence match based on the unique ID substring.
