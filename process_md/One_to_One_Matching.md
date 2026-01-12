One-to-One Matching (Simple)
===========================

Overview
--------
The simplest form of matching that pairs transactions based on exact amounts and high semantic overlap. It serves as a precursor or fallback to the more complex Enhanced/Hungarian methods.

Key file
--------
- `Raas_Plus/unified_reconciliation.py`

Algorithm Logic
---------------
This documentation covers the general concept of 1-to-1 matching used throughout the pipeline.
1. **Identity Check**: Checks if a single bank record can be uniquely identified as a company record.
2. **Core Components**:
   - **Exactness**: Prioritizes equality in references and amounts.
   - **Uniqueness**: Ensures the match doesn't prevent a better global optimization.
3. **Scoring**: Usually ranges from 90% to 100% depending on the specific 1:1 sub-strategy used (Enhanced, ID-based, or Exact).

Inputs
------
- `Amount`, `Date`, `Reference`

Outputs
-------
- **Match Type**: `1:1`
- **Match Score**: Variable (90-100%).

Notes
-----
For the specific technical implementation of the primary 1:1 strategy, see [Exact_Matching.md](file:///c:/Users/Lenovo/OneDrive - Cognitive Consulting Sdn Bhd (1)/Desktop/SegmentationCompressionWork/PlayWright-Extractor/process_md/Exact_Matching.md).
