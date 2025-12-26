Match Statement Explanation
===========================

Overview
--------
This step reads the RaasPlus output Excel and applies those matches
in the UI. It is the final step that marks items as matched.

Key files
---------
- `playwright_scripts/MatchStatement_Optimized.py`

Inputs
------
- Match-result Excel from RaasPlus (`matchresultpath`)
- Account name and credentials

Outputs
-------
- UI matches applied in Acumatica
- Log file under `logs/runs/`
- `failed_entries.xlsx` if some items could not be matched

High-level flow
---------------
1) Load match-result Excel and read sheets
2) Process special reverse CE/GL matches first
3) Process 1-to-1 matches
4) Process group matches (1-to-many)
5) Click "Process" to finalize in UI

How it uses the Excel
---------------------
- Sheet "1to1 Matches" -> `process_1to1_matches(...)`
- Sheet "Group Match" -> `process_group_matches(...)`
  - Skips `reverse_ce_gl` rows in this step (handled earlier)
