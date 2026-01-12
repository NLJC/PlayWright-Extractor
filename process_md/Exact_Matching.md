Exact Matching (Enhanced 1-to-1)
===============================

Overview
--------
The Enhanced 1-to-1 Matching algorithm (Exact Matching) identifies the best single company transaction to match against a single bank transaction. It uses a weighted scoring mechanism based on amount, date proximity, reference numbers, and description similarity.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_exact_matches`)

Algorithm Logic
---------------
1. **Filtering**: For each unmatched bank transaction, the engine identifies potential company candidates that share the same transaction type (Credit/Debit) and have a non-zero net amount.
2. **Scoring**: Each candidate is assigned a total score ($S$) based on four weighted components:
   - **Amount Score ($S_a$ - Weight: 0.5)**: 
     - $1.0$ if the amounts match exactly.
     - Otherwise, calculated as $max(0, 1 - (\text{Amount Diff} / \text{Target Amount}) / \text{Tolerance})$.
   - **Date Score ($S_d$ - Weight: 0.2)**: 
     - Calculated as $max(0, 1 - (\text{Days Diff} / \text{Date Tolerance Days}))$.
   - **Reference Score ($S_r$ - Weight: 0.2)**:
     - Exact match: 1.0
     - Partial "contains" match: 0.9
     - Last 6 digits match: 0.8
     - Fuzzy match ($>$90% similarity): 0.8
   - **Description Score ($S_s$ - Weight: 0.1)**:
     - Based on `fuzz.token_set_ratio` similarity between bank and company descriptions.

3. **Guards**:
   - **Group Evidence Guard**: Skips 1:1 matching if the transaction is flagged as likely belonging to a group (n:1 or 1:n).
   - **Reservation Guard**: Defer 1:1 if adding a nearby candidate would result in a better group sum.

4. **Selection**: Picks the candidate with the highest score $S \geq 0.7$.

Inputs
------
### Bank Dataset
- `Bank_Amount` (Target for matching)
- `Bank_Date`
- `Bank_Ref_Field` or `Bank_TXN_ID_Field` (References)
- `Bank_Desc_Field` (Description)

### Company Dataset
- `net_amount`
- `Doc. Date`
- `Document Ref.` (Reference)
- `Description`

Outputs
-------
- **Match Type**: `enhanced_1to1`
- **Result**: A 1-to-1 link between `bank_tx_id` and `company_tx_id`.
- **Match Score**: Cumulative percentage based on weights.
- **Explanation**: Breakdown of component scores (e.g., "Amount score: 1.00, Date score: 0.95...").

Example
-------
| Source | Date | Reference | Amount |
| :--- | :--- | :--- | :--- |
| **Bank** | 2023-10-01 | **REF123456** | **1,500.00** |
| **Company** | 2023-09-30 | **INV-REF123456** | **1,500.00** |

**Matching Result:**
- **Status**: Matched
- **Score**: ~98% (Exact amount match, 1-day date diff, partial reference match).
- **Explanation**: "Amount score: 1.00, Date score: 0.93, Ref score: 0.90 (Partial reference match: REF123456 in INV-REF123456)..."
