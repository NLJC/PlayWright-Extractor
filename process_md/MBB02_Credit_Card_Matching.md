MBB02 Credit Card Matching
==========================

Overview
--------
A specialized reconciliation logic for MBB02 bank statements involving credit card transaction deposits. It maps consolidated bank deposits back to individual transaction references extracted from supporting credit card transaction files.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_mbb02_creditcard_group_matches`)

Algorithm Logic
---------------
1. **Bank Description Parsing**:
   - The engine identifies bank rows where the description contains credit card deposit metadata (e.g., Terminal ID, Date, Batch Number).
   - Uses `mbb02_cc.parse_mbb02_tran_desc` to extract these details.
2. **Metadata Enrichment**:
   - For each identified deposit, the engine searches the `MBB02_CC_INPUT_FOLDER` (default: `CreditCardTransaction`) for supporting transaction files matching the description.
   - It extracts every **Reference Number** and the individual transaction amounts from these supporting files.
3. **Company Validation**:
   - **Crucial Rule**: Every reference identified in the supporting document **must exist** as an unmatched transaction in the company statement.
   - If any reference is missing, the match is rejected, and the missing references are recorded in a specialized error log for the analyst.
4. **Reconciliation**:
   - Once all references are verified, the engine matches the single bank deposit against the group of company transactions.

Inputs
------
### Bank Dataset
- `Description`: Must contain MBB02 deposit strings.
- `Receipt`: The deposit amount.

### Supporting Files (`CreditCardTransaction/`)
- Excel/CSV files containing individual transaction details and references.

### Company Dataset
- `Document Ref.`: Must contain the references listed in the supporting files.

Outputs
-------
- **Match Type**: `mbb02_cc_group`.
- **Result**: N-to-1 match.
- **Special**: Detailed error logging if specific references within the deposit are missing from the company records.

Example
-------
**Bank Statement**:
- Desc: `CC DEP 12345678 231010` | Amount: 5,000.00

**Supporting File**:
- Ref: `TXN-001` | Amount: 2,000.00
- Ref: `TXN-002` | Amount: 3,000.00

**Company Statement**:
- [MUST contain `TXN-001` and `TXN-002`]

**Result**: Matched (N:1) if both `TXN-001` and `TXN-002` are found in the company records.
