JomPAY CR Group Matching
=========================

Overview
--------
This algorithm handles specific JomPAY batch credit (CR) transactions. It reconciles a single consolidated bank credit against multiple company receipts based on a pre-defined JSON payload containing the grouping logic.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_jompay_cr_group_matches_from_json`)

Algorithm Logic
---------------
1. **JSON Payload**: The engine reads a configuration file (e.g., `json/phase1_jompay_consolidated.json`) which contains groups of JomPAY reference numbers and their expected totals.
2. **Company Side (N)**:
   - For each group in the JSON, the engine filters unmatched company transactions by the listed `jompay_ref_nos`.
   - **Constraints**:
     - All company records must have the **exact same date** as specified in the JSON.
     - The **sum of Receipt** amounts must exactly match the `total_amount` in the JSON.
3. **Bank Side (1)**:
   - Searches for a single bank transaction with description `AUTOPAY CR`.
   - **Date Constraint**: The bank transaction must occur exactly **one day after** the date specified in the JSON.
   - **Amount Constraint**: The bank's `net_amount` must exactly match the `total_net_amount` in the JSON.
4. **Result**: If both sides match their respective JSON criteria, an N-to-1 match is produced.

Inputs
------
### JSON Group Payload
- `date`: The processing date.
- `jompay_ref_nos`: List of references to look for in the company data.
- `total_amount`: Expected sum of company receipts.
- `total_net_amount`: Expected bank transaction amount.

### Company Dataset
- `Document Ref.`: Must match `jompay_ref_nos`.
- `Doc. Date`: Must match JSON `date`.
- `Receipt`: Sum must match `total_amount`.

### Bank Dataset
- `Tran. Desc`: Must be `AUTOPAY CR`.
- `Tran. Date`: Must be JSON `date` + 1 day.
- `net_amount`: Must match `total_net_amount`.

Outputs
-------
- **Match Type**: `jompay_cr_group`
- **Result**: N-to-1 match (Multiple company IDs -> Single bank ID).
- **Match Score**: 100.0 (Rules-based exact matching).

Example
-------
**JSON Group**: {Date: 2023-11-01, Refs: [JP001, JP002], Total: 500.00, Net: 500.00}

| Source | Date | Ref/Desc | Amount |
| :--- | :--- | :--- | :--- |
| **Company 1** | 2023-11-01 | **JP001** | 300.00 |
| **Company 2** | 2023-11-01 | **JP002** | 200.00 |
| **Bank** | 2023-11-02 | **AUTOPAY CR** | 500.00 |

**Match Outcome**: Successful N-to-1 match.
