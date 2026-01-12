Amount and Date Matching
========================

Overview
--------
A fallback matching strategy that focuses on finding matches based on exact amount and date proximity when reference numbers are missing or inconsistent.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_amount_date_matches`)

Algorithm Logic
---------------
1. **Hard Constraints**:
   - **Amount**: Must be an exact match (respecting `AMOUNT_TOLERANCE`).
   - **Date**: Must fall within a specific window (defined by `DATE_TOLERANCE_DAYS`).
2. **Filtering**: Identifies all unmatched company records where $| \text{Bank Amount} - \text{Company Amount} | \leq \text{Tolerance}$ and the date is within range.
3. **Selection**: If multiple candidates exist, it picks the one with the smallest absolute date difference (closest in time).
4. **Scoring**:
   - Base score: 85%
   - Date Bonus: Up to 10% based on proximity ($1 - (\text{Diff} / \text{Tolerance})$).
   - Final scores typically range from 85% to 95%.

Inputs
------
### Bank Dataset
- `Bank_Amount` (Exact match target)
- `Bank_Date`

### Company Dataset
- `net_amount` (Must match bank amount)
- `Doc. Date` (Must be within tolerance window)

Outputs
-------
- **Match Type**: `amount_date`
- **Result**: 1-to-1 match.
- **Explanation**: "Exact amount match (X.XX) with date difference of Y days".

Example
-------
| Source | Date | Amount |
| :--- | :--- | :--- |
| **Bank** | 2023-10-05 | **2,450.00** |
| **Company A** | 2023-10-03 | **2,450.00** |
| **Company B** | 2023-10-06 | **2,450.00** |

**Matching Result**:
- Matches with **Company B** (1-day diff) over Company A (2-day diff).
- **Match Score**: ~94%
- **Type**: `amount_date`
