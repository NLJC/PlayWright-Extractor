Hungarian 1-to-1 Matching
=========================

Overview
--------
This algorithm provides a global optimal solution for 1-to-1 matching across the entire pool of unmatched transactions. Unlike greedy algorithms that pick the best match for each row sequentially, the Hungarian algorithm minimizes the total cost (or maximizes the total score) for all matches simultaneously.

Key file
--------
- `Raas_Plus/unified_reconciliation.py` (Method: `find_hungarian_1to1_matches`)

Algorithm Logic
---------------
1. **Pairwise Scoring**: The engine computes a similarity score for every possible pair $(B_i, C_j)$ where $B_i$ is a bank transaction and $C_j$ is a company transaction.
   - **Similarity Metrics**: Uses the same weighted scoring as Exact Matching (Amount, Date, Reference, Description).
   - **Pruning**: To avoid $O(N^2)$ complexity, it uses an `amount_gate` and `top_k` candidates per bank row to prune impossible pairs.
2. **Optimization**:
   - If `scipy` is available, it uses the linear sum assignment (Hungarian) algorithm to find the optimal global match.
   - If `scipy` is unavailable, it falls back to a "mutual-best" greedy heuristic.
3. **Scoring Components**:
   - **Amount Weight**: 0.5
   - **Date Weight**: 0.2
   - **Reference Weight**: 0.2
   - **Description Weight**: 0.1

Inputs
------
### Bank Dataset
- `Bank_Amount`, `Bank_Date`, `Bank_Ref`, `Bank_Desc`

### Company Dataset
- `net_amount`, `Doc. Date`, `Document Ref.`, `Description`

Outputs
-------
- **Match Type**: `hungarian_1to1`
- **Result**: A globally optimized 1-to-1 mapping.
- **Match Score**: Cumulative score based on weights.

Example
-------
Given two bank transactions ($B_1, B_2$) and two company transactions ($C_1, C_2$):
- $B_1$ scores 0.9 with $C_1$ and 0.85 with $C_2$.
- $B_2$ scores 0.88 with $C_1$ and 0.2 with $C_2$.

**Greedy Match**: $B_1$ takes $C_1$ (0.9), leaving $B_2$ with $C_2$ (0.2). Total score: **1.1**.
**Hungarian Match**: $B_1$ takes $C_2$ (0.85), allowing $B_2$ to take $C_1$ (0.88). Total score: **1.73**.

The Hungarian algorithm chooses the second option as it optimizes the overall result.
