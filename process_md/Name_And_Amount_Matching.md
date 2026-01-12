Name and Amount Matching
========================

Overview
--------
Matches transactions based on the similarity of names or descriptions when reference numbers are missing. It uses a weighted scoring mechanism that prioritizes name matches over date and amount proximity.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_name_and_amount_matches`)

Algorithm Logic
---------------
1. **Name Extraction**:
   - **Bank Fields**: Scans `Customer Reference`, `Recipient Reference`, `Other Payment Detail`, `Sender Name`, and `Tran. Desc`.
   - **Company Fields**: Scans `Business Account Name`, `Business Account`, and `Description`.
2. **Scoring Logic**:
   - **Name Score (60%)**: 
     - Exact match: 100
     - Partial "contains" match: 90
     - Fuzzy similarity (`token_set_ratio`): 0-100
   - **Date Score (20%)**: Based on proximity within the tolerance window.
   - **Amount Score (20%)**: Based on proximity (must be within tolerance).
3. **Threshold**: Only pairs with a **Name Score $\geq$ 70** and a **Combined Score $\geq$ 0.7** are considered.
4. **Guards**: Applies Group Evidence and Reservation guards to ensure the 1:1 match is the most optimal use of these transactions.

Inputs
------
### Bank Dataset
- `Sender Name`, `Recipient Reference`, `net_amount`, `Date`

### Company Dataset
- `Business Account Name`, `Description`, `net_amount`, `Date`

Outputs
-------
- **Match Type**: `name_and_amount`
- **Match Score**: Combined weighted score (0-100).
- **Explanation**: "Matched name: [Bank Name] ~ [Company Name]. Total score: X".

Example
-------
| Source | Description | Amount |
| :--- | :--- | :--- |
| **Bank** | **SENDER: ALICE TAN** | 500.00 |
| **Company**| **ALICE TAN PTE LTD** | 500.00 |

**Result**: Matched (90% name score due to "Alice Tan" containment).
