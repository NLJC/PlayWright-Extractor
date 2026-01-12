Reverse CE-GL Process
======================

Overview
--------
A specialized internal reconciliation step within the **Company Dataset** itself. It identifies "Cash Entry" or "GL Entry" records that have been reversed or corrected before they ever hit the bank statement.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_reverse_ce_gl_matches`)

Algorithm Logic
---------------
1. **Dataset Internal Search**: Only looks at company transactions that have already been unmatched.
2. **Filtering**: Focuses on transactions labeled as `Cash Entry` or `GL Entry`.
3. **Pairing Logic**:
   - Groups records by their **Document Reference**.
   - Within each group, it looks for pairs where:
     - One record has a **positive** amount and the other has an **identical negative** amount (e.g., 500.00 and -500.00).
     - These represent a transaction and its subsequent reversal.
4. **Outcome**: The pair is matched together to "net them out", preventing them from cluttering the bank reconciliation process. **No bank transaction is involved.**

Inputs
------
### Company Dataset
- `Tran. Type`: Cash Entry / GL Entry.
- `Document Ref.`: Used for grouping pairs.
- `Receipt` / `Disbursement`: Used to find offsetting values.

Outputs
-------
- **Match Type**: `reverse_ce_gl`
- **Bank TX ID**: `None`
- **Company TX ID**: List containing the IDs of both the original and reversal entry.
- **Match Score**: 95.0.

Example
-------
| Date | Ref | Type | Amount |
| :--- | :--- | :--- | :--- |
| 2023-10-01 | **ADJ-001** | **Cash Entry** | **150.00** |
| 2023-10-02 | **ADJ-001** | **Cash Entry** | **-150.00** |

**Result**: Both entries are matched to each other and removed from the active reconciliation pool.
