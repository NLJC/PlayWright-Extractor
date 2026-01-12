Group Matching (Generic)
========================

Overview
--------
A multi-stage engine designed to find complex 1-to-N (one bank transaction to many company transactions) or N-to-1 relationships. It uses semantic similarity and greedy accumulation to resolve fragmented payments.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_group_matches`)

Algorithm Logic
---------------
The group matching process follows three sequential strategies:

### 1. Semantic Grouping (`_find_semantic_group_matches`)
- **Strategy**: For an unmatched transaction, it gathers the top-K candidates from the opposite dataset using semantic similarity (Description + Reference).
- **Matching**: It greedily adds candidates to a group as long as their cumulative amount approaches the target amount without exceeding it.
- **Preference**: Higher similarity candidates are added first.

### 2. One-to-Many Matching (`_find_one_to_many_matches`)
- **Strategy**: Searches for combinations of company transactions that sum exactly to a single bank transaction.
- **Constraint**: Uses a date-window constraint and prioritizes candidates with matching references.

### 3. Many-to-One Matching (`_find_many_to_one_matches`)
- **Strategy**: Symmetric to One-to-Many; searches for groups of bank transactions (e.g., decentralized deposits) that sum to a single company record.

Inputs
------
### Bank Dataset
- `Description`, `Reference`, `net_amount`, `Date`

### Company Dataset
- `Description`, `Reference`, `net_amount`, `Date`

Outputs
-------
- **Match Type**: `semantic_group`, `one_to_many`, or `many_to_one`.
- **Match Score**: Based on amount accuracy and semantic weight.
- **Explanation**: Lists the IDs of all transactions in the group and the total amount.

Example (1-to-N)
----------------
**Bank Entry**:
- 2023-10-01 | **Vendor Payment** | **3,500.00**

**Company Entries**:
- 2023-10-01 | Inv #101 | 1,500.00
- 2023-10-02 | Inv #102 | 2,000.00

**Result**: Matched (1:2)
- Total Company Sum: 3,500.00 (Perfect Match).
- Explanation: "Company sum (3500.00) matches bank amount (3500.00)".
