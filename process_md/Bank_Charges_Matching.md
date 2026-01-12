Bank Charges Matching
=====================

Overview
--------
Automatically identifies and flags transactions likely to be bank fees, commissions, or taxes. These transactions are typically recorded in the bank statement but may not have a direct corresponding entry in the company statement at the time of reconciliation.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_bank_charges`)

Algorithm Logic
---------------
1. **Keyword Filtering**: The engine scans the bank transaction's **Description** field for specific keywords:
   - *Keywords*: charge, fee, commission, service charge, interest, admin fee, bank charge, handling fee, transfer fee, maintenance, gst, vat, tax, levy, processing, chq, etc.
2. **Amount Constraint**:
   - The transaction must be a **disbursement** (debit).
   - The amount must be **below 100.00** (default safety threshold to avoid flagging large legitimate payments).
   - The receipt (credit) amount must be zero.
3. **Outcome**: Transactions matching these criteria are flagged as `bank_charge`. No company transaction is linked (`company_tx_id` is set to "N/A").

Inputs
------
### Bank Dataset
- `Description` (Keyword search)
- `Disbursement` (Amount < 100)
- `Receipt` (Must be 0)

Outputs
-------
- **Match Type**: `bank_charge`
- **Company ID**: "N/A"
- **Match Score**: 80.0
- **Explanation**: "Bank charge detected. Description: [Description Text]"

Example
-------
| Source | Date | Description | Disbursement |
| :--- | :--- | :--- | :--- |
| **Bank** | 2023-10-15 | **SERVICE CHARGE OCT** | **5.00** |

**Result**: Automatically flagged as a bank charge with 80% confidence.
