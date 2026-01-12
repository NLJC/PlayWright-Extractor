Custom Structured Group Matching
================================

Overview
--------
This algorithm is designed for "AUTOPAY DR" transactions that share common metadata but are recorded as multiple entries in the bank statement and a single consolidated entry in the company statement.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_custom_structured_group_matches`)

Algorithm Logic
---------------
1. **Bank Grouping (N)**:
   - Filter bank transactions with description `AUTOPAY DR`.
   - Group them by **External Reference Number** and **Transaction Date**.
   - **Constraint**: The group must contain at least 2 entries (default).
2. **Company Target (1)**:
   - For each bank group, calculate the `group_sum` (sum of net amounts).
   - Search for a single company transaction with the same `txn_type`.
   - **Date Constraint**: By default, requires the **exact same date** as the bank group (can be relaxed via configuration).
   - **Amount Constraint**: The company transaction's `net_amount` must equal the `group_sum` (within `AMOUNT_TOLERANCE`).
3. **Tie-Breaker**: If multiple company candidates exist, the engine prefers the one whose description or reference has the highest fuzzy similarity to the bank's reference number.

Inputs
------
### Bank Dataset
- `Tran. Desc`: Must be `AUTOPAY DR`.
- `Ext. Ref. Nbr.`: Used for grouping.
- `Tran. Date`: Used for grouping.
- `net_amount`: Summed for the group.

### Company Dataset
- `Doc. Date`: Date matching.
- `net_amount`: Must match bank group sum.
- `Description` / `Document Ref.`: Used for tie-breaking.

Outputs
-------
- **Match Type**: `custom_structured_group`
- **Result**: N-to-1 match (Multiple bank IDs -> Single company ID).
- **Match Score**: 100.0.

Example
-------
**Bank Entries (N)**:
- 2023-10-10 | REF-ABC | AUTOPAY DR | 100.00
- 2023-10-10 | REF-ABC | AUTOPAY DR | 150.00
- **Total**: 250.00

**Company Entry (1)**:
- 2023-10-10 | Consolidated Payment | 250.00

**Result**: Both bank entries are matched to the single company entry.
