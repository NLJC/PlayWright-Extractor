# PlayWright Test Scripts

Quick debug scripts for testing individual components of the MatchStatement RPA process.

## Available Test Scripts

### 1. test_main_flow.py - **COMPLETE RPA FLOW TEST**
**NEW: Tests the entire production flow from start to finish**

```bash
python playwright_test/test_main_flow.py
```

**What it tests:**
- Browser initialization and login
- **Reverse CE/GL matching (processed FIRST)**
- Navigation to Process Bank Records
- 1-to-1 matching
- Group matching (regular, non-reverse CE/GL)
- Complete error handling and failed entries tracking

**Edit the test data:**
```python
test_1to1_data = {
    "Bank Reference Number": ["TEST001"],
    "CSGP Reference": ["REF001"],
}

test_group_data = {
    "Bank Reference Number": ["TEST002"],
    "CSGP Reference": ["REF002,REF003"],
    "reverse_ce_gl": [False]
}

test_reverse_cegl_data = {
    "Bank Reference Number": ["TEST003", "TEST003"],
    "CSGP Reference": ["11092025", "11092025"],
    "reverse_ce_gl": [True, True]
}
```

**Execution Order (matches production):**
1. Initialize browser and login
2. **Process Reverse CE/GL matches FIRST** (Reconciliation Statements)
3. Navigate to Process Bank Records
4. Process 1-to-1 matches
5. Process Group matches (excluding reverse CE/GL)
6. Display summary of failed entries

---

### 2. test_reverse_cegl.py - **REVERSE CE/GL MATCHING TEST**
Tests the reverse CE/GL matching process with full reconciliation flow.

```bash
python playwright_test/test_reverse_cegl.py
```

**What it tests:**
- Navigation to Reconciliation Statements
- Account selection (filtering for "On Hold" status)
- DETAILS tab verification
- Document Ref filtering with smart waiting
- Row detection after filtering
- **Checkbox detection and clicking** (with multiple strategies)
- Reconciliation validation (matching descriptions)
- **Save button clicking**

**Edit the test data:**
```python
test_pairs = [
    ["11092025", "11092025"],  # Pairs of CSGP refs for reverse CE/GL
    # Add more pairs as needed
]
```

**Key Features:**
- Smart waiting (proceeds as soon as page loads, not full 25 seconds)
- Comprehensive DEBUG logging showing:
  - Table selectors tried
  - Row counts found
  - Cell HTML for checkbox detection
  - Filter operations
- Tests complete flow: search → validate → click checkboxes → save

---

### 3. test_1to1_matching.py - **1-TO-1 MATCHING TEST**
Tests individual 1-to-1 matches in Process Bank Records.

```bash
python playwright_test/test_1to1_matching.py
```

**What it tests:**
- Navigation to Process Bank Records
- Account selection with smart waiting
- Filtering by Bank Reference Number
- Matching with CSGP Reference
- Match to Payments tab operations

**Edit the test data:**
```python
test_data = {
    "Bank Reference Number": ["12345"],  # Replace with actual bank ref
    "CSGP Reference": ["67890"],         # Replace with actual CSGP ref
}
```

---

### 4. test_group_matching.py - **GROUP MATCHING TEST**
Tests group matches (1-to-many) in Process Bank Records.

```bash
python playwright_test/test_group_matching.py
```

**What it tests:**
- Navigation to Process Bank Records
- Account selection with smart waiting
- Filtering by Bank Reference Number
- Matching with multiple CSGP References
- Enable Multiple Matching checkbox
- Match to Payments tab operations

**Edit the test data:**
```python
test_data = {
    "Bank Reference Number": ["12345"],
    "CSGP Reference": ["67890,67891,67892"],  # Comma-separated multiple refs
    "Match Type": ["group"]
}
```

---

### 5. test_navigation.py - **BASIC NAVIGATION TEST**
Tests login and basic navigation to verify system access.

```bash
python playwright_test/test_navigation.py
```

**What it tests:**
- Browser initialization
- Login process
- Iframe detection
- Account link detection
- Navigation to Process Bank Records
- Navigation to Reconciliation Statements

---

## Environment Configuration

All tests use environment variables from `env 1` file:

```bash
WEBSITE_URL = https://csmstg.censof.com/DBKK
WEBSITE_USERNAME = rpauser
PASSWORD = Rp@12345
accountName = CIM02

# Wait time in milliseconds (maximum, smart wait proceeds earlier)
PAGE_WAIT_TIME_MS = 25000
```

### Smart Waiting Feature ⚡

**NEW:** All tests now use **smart waiting** instead of fixed timeouts!

**How it works:**
- Detects when pages are ready using `networkidle` state
- Proceeds as soon as loading completes (typically 2-5 seconds)
- Falls back to `PAGE_WAIT_TIME_MS` only if needed
- **Results in 70-80% faster test execution**

**Example:**
```python
# OLD: Always waits full 25 seconds
processor.page.wait_for_timeout(25000)

# NEW: Proceeds as soon as ready (usually 2-5 seconds)
processor.smart_wait_for_page_load()
```

---

## Usage Tips

1. **All tests run with visible browser** (`headless=False`) so you can see what's happening
2. **Press Enter to close** the browser after test completes - gives you time to inspect the results
3. **Edit test data** at the top of each script to test specific scenarios
4. **Check console output** for detailed logging of each step
5. **Watch DEBUG messages** for troubleshooting selector issues

---

## Debugging Tips

### Enable DEBUG Logging

The scripts output detailed DEBUG logs showing:
- Table selectors tried and which ones succeeded
- Row counts found after filtering
- Cell HTML snippets for checkbox detection
- Filter operations and their results
- Checkbox detection strategies

Watch for `[DEBUG]` messages in the output.

### Common Issues & Solutions

**Issue: "Could not find table"**
- ✓ Check if the DETAILS tab is active
- ✓ Verify the table selector in DEBUG output
- ✓ Wait time might be too short (increase `PAGE_WAIT_TIME_MS`)

**Issue: "Found 0 rows after filtering"**
- ✓ Check if filter was applied successfully (`[OK] Filtered Document Ref.`)
- ✓ Verify the Document Ref value exists in the system
- ✓ Look at DEBUG output showing table HTML structure
- ✓ Try increasing wait time after filtering

**Issue: "Could not find Reconciled checkbox"**
- ✓ Check DEBUG output showing "First cell HTML"
- ✓ Verify checkbox is in the first column of the table
- ✓ Look at row HTML snippet in DEBUG output
- ✓ May need to adjust checkbox detection strategy

**Issue: "Save button not found"**
- ✓ Verify you're on the correct page (Reconciliation Statements)
- ✓ Check if checkboxes were clicked successfully first
- ✓ Look at DEBUG output for available button selectors

---

## Test Output Format

All tests use consistent output formatting:

- `[OK]` - Successful operation
- `[ERROR]` - Error occurred
- `[WARNING]` - Warning message (operation continued)
- `[DEBUG]` - Debug information (detailed technical info)
- `[INFO]` - Informational message

Example output:
```
[INFO] Searching for Document Ref: 11092025
[DEBUG] Found grid container: #ctl00_phG_tab_t0_grid1
[DEBUG] Grid '#ctl00_phG_tab_t0_grid1' + selector 'tr.GridRow': found 5 rows
[OK] Found 5 rows using grid '#ctl00_phG_tab_t0_grid1' + selector 'tr.GridRow'
[INFO] Found 5 matching records
```

---

## Requirements

Before running tests:

1. **Activate virtual environment:**
   ```bash
   cd d:\Github\PlayWright-Extractor
   source venv/Scripts/activate  # Linux/Mac
   # or
   venv\Scripts\activate  # Windows
   ```

2. **Ensure all dependencies installed:**
   ```bash
   pip install playwright pandas python-dotenv
   playwright install chromium
   ```

3. **Update `env 1` with correct credentials**

---

## Best Practices for Testing

1. **Start with test_navigation.py** to verify login works
2. **Test individual components** before running main flow
3. **Use real data from your matching results** for accurate testing
4. **Start with small datasets** (1-2 records) before testing full batches
5. **Review DEBUG output** when something doesn't work
6. **Keep browser window visible** to see what's happening

---

## Quick Start Guide

**First time testing?** Follow these steps:

1. Run navigation test:
   ```bash
   python playwright_test/test_navigation.py
   ```

2. If login works, test reverse CE/GL:
   ```bash
   python playwright_test/test_reverse_cegl.py
   ```

3. Test 1-to-1 matching:
   ```bash
   python playwright_test/test_1to1_matching.py
   ```

4. Finally, test complete flow:
   ```bash
   python playwright_test/test_main_flow.py
   ```

---

## Support

For issues or questions:
1. ✓ Check DEBUG output in test results
2. ✓ Verify environment variables in `env 1`
3. ✓ Ensure you have access to the test account
4. ✓ Check if test data exists in the system
5. ✓ Review the console output for error messages
