MBB02 Credit Card Matching
==========================

Overview
--------
This is a custom Stage 1 matcher that groups MBB02 credit card deposits
by reading supporting credit card files and matching their references
against company statements.

Key files
---------
- `Raas_Plus/unified_reconciliation.py`
- `scripts/mbb02_cr_dr_matching.py`

When it runs
------------
- `BANK_NAME == "MBB02"`
- `ENABLE_MBB02_CC_GROUPING == True`
- `CreditCardTransaction/` folder exists

Algorithm summary
-----------------
1) Parse bank "Tran. Desc" for:
   - CR/DR + number + date (ddmmyyyy)
2) Scan all credit card files under `CreditCardTransaction/`:
   - Match C14 trailing digits to bank number
   - Match B4 date to bank date
   - Extract all "Reference No" values
3) Ensure every reference exists in company statements
4) Select company rows in order (no reuse)
5) Check net amount consistency
6) Emit a group match:
   - `Match Type` = `mbb02_creditcard_group`

Hypothetical example
--------------------
Bank row:
- Tran. Desc: "CR/CARD SALES MN 07700511 DATED 01072025"
- Receipt: 10,000.00
- Disbursement: 0.00

Credit card file:
- C14: "MBB CARD SETTLEMENT 123407700511"
- B4: "01/07/2025"
- Reference No: REF1001, REF1002, REF1003
- Last row O (net): 10000.00

Company statements:
- Document Ref. REF1001 (Receipt 3,000.00)
- Document Ref. REF1002 (Receipt 2,000.00)
- Document Ref. REF1003 (Receipt 5,000.00)

Result:
- Group match with CSGP refs: REF1001, REF1002, REF1003
- Bank net == company net == 10,000.00

How it reaches Playwright
-------------------------
The output Excel "Group Match" sheet includes a row with:
- `Match Type` = `mbb02_creditcard_group`
- `CSGP Reference` = "REF1001, REF1002, REF1003"

`MatchStatement_Optimized.process_group_matches(...)` applies those
matches in the UI with multiple-matching enabled.
