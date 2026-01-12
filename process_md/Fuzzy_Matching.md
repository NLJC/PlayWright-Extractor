Fuzzy Matching
==============

Overview
--------
A fallback 1-to-1 matching strategy that aligns transactions based on description similarity when exact references are missing or mismatched.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_fuzzy_matches`)

Algorithm Logic
---------------
1. **Filtering**: Identifies unmatched bank transactions and gathers company candidates that:
   - Share the same `txn_type`.
   - Fall within the **Amount Tolerance** ($| \Delta Amt | \leq Tol$).
   - Fall within the **Date Tolerance** ($| \Delta Date | \leq Tol Days$).
2. **Text Similarity**: For each candidate, the engine calculates a fuzzy similarity score between the bank description and the company description using `fuzz.token_set_ratio`.
3. **Selection**:
   - Picks the candidate with the highest similarity score.
   - **Constraint**: The score must exceed the `MIN_FUZZY_SCORE` (default: 80-90).
4. **Guards**: Applies the Group Evidence and Reservation guards to ensure the transaction doesn't better serve a group match.

Inputs
------
### Bank Dataset
- `Description`
- `net_amount`
- `Date`

### Company Dataset
- `Description`
- `net_amount`
- `Date`

Outputs
-------
- **Match Type**: `fuzzy`
- **Result**: 1-to-1 match.
- **Match Score**: The fuzzy similarity score (0-100).
- **Explanation**: "Fuzzy match with score X/100. Net amount: [Bank] vs [Company]".

Example
-------
| Source | Date | Description | Amount |
| :--- | :--- | :--- | :--- |
| **Bank** | 2023-11-05 | **PYMT FROM J SMITH** | 1,200.00 |
| **Company**| 2023-11-04 | **JOHN SMITH PAYMENT** | 1,200.00 |

**Result**: Matched (Fuzzy)
- **Score**: ~85 (High token overlap: "Smith", "Payment/Pymt").
