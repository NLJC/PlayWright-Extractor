Bulk EFT Matching
=================

Overview
--------
Handles consolidated payments (typically disbursements) where the bank provides a specific "L+yymm+EFT" reference pattern, and the company statement contains the raw EFT number.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_bulk_eft_matches`)

Algorithm Logic
---------------
1. **Bank Pattern Extraction (N)**:
   - Identify bank transactions matching the regex: `^L(\d{4})(\d{6,12})$` (e.g., `L2508055380812`).
   - Group by the full reference.
   - Extract the core **EFT number** from the end of the string (e.g., `055380812`).
2. **Company Search (1)**:
   - Search for a single company transaction with `txn_type` = `disbursement`.
   - **Reference Constraint**: The company's `Document Ref.` or `Description` must **contain** the extracted EFT number.
3. **Reconciliation**:
   - Compare the **Bank Group Sum** against the **Company Amount**.
   - **Scenario A (Exact)**: Difference is within tolerance. Type: `custom_bulk_eft`.
   - **Scenario B (With Rejects)**: Significant difference exists. Type: `custom_bulk_eft_with_rejects`. This allows the match to be recorded while highlighting discrepancies for manual review.

Inputs
------
### Bank Dataset
- `Ext. Ref. Nbr.`: Pattern `L` + `YYMM` + `EFT#`.
- `net_amount`: Summed for the group.

### Company Dataset
- `Document Ref.` / `Description`: Must contain the `EFT#`.
- `net_amount`: Target for matching the group sum.

Outputs
-------
- **Match Type**: `custom_bulk_eft` or `custom_bulk_eft_with_rejects`.
- **Result**: N-to-1 match.
- **Explanation**: Includes the extracted EFT number and any amount difference.

Example
-------
**Bank Group**:
- `L2310055380812` | 1,000.00
- `L2310055380812` | 2,000.00
- **EFT Number**: `055380812`

**Company Record**:
- `Ref: WEB-PAY-055380812` | 3,000.00

**Result**: Matched (N:1).
