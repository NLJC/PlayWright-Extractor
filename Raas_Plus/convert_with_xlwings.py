import os
import json
# import xlwings as xw
from datetime import datetime, date
import traceback

def clean_value(val):
    """Clean and convert values for JSON serialization."""
    if val is None or val == '':
        return None
    if isinstance(val, (int, float)):
        return int(val) if val == int(val) else val
    if isinstance(val, datetime):
        return val.strftime("%Y-%m-%d")
    return str(val).strip()

def parse_date(date_str):
    """Parse date string in various formats to YYYY-MM-DD."""
    if not date_str or date_str == '':
        return None
        
    date_str = str(date_str).strip()
    date_formats = [
        "%Y-%m-%d",  # YYYY-MM-DD
        "%d/%m/%Y",  # DD/MM/YYYY
        "%m/%d/%Y",  # MM/DD/YYYY
        "%Y%m%d",    # YYYYMMDD
        "%d-%b-%y",  # DD-MMM-YY
        "%d-%b-%Y",  # DD-MMM-YYYY
        "%d %b %Y",  # DD MMM YYYY
        "%Y/%m/%d",  # YYYY/MM/DD
    ]
    
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str.split()[0], fmt)
            return dt.strftime("%Y-%m-%d")
        except (ValueError, AttributeError):
            continue
    return date_str  # Return original if no format matches

def convert_excel_to_json(excel_path, output_dir):
    """Convert Excel file to JSON format using xlwings."""
    print(f"\nProcessing file: {excel_path}")
    app = None
    
    try:
        import xlwings as xw
        # Start Excel application
        app = xw.App(visible=False)
        
        # Open the workbook
        wb = app.books.open(excel_path)
        sheet = wb.sheets[0]  # Get first sheet
        
        # Get all used range
        last_cell = sheet.used_range.last_cell
        last_row = last_cell.row
        last_col = last_cell.column
        
        # Get headers (first row)
        headers = []
        for col in range(1, last_col + 1):
            cell_value = sheet.range(1, col).value
            headers.append(str(cell_value).strip() if cell_value is not None else f"Column_{col}")
        
        print(f"Found {last_row-1} rows and {last_col} columns")
        print(f"Columns: {', '.join(headers)}")
        
        # Identify date columns
        date_columns = [i for i, h in enumerate(headers, 1) 
                       if any(term in h.lower() for term in ['date', 'doc. date', 'tran. date'])]
        
        # Convert rows to dictionaries
        data = []
        for row in range(2, last_row + 1):  # Skip header row
            row_data = {}
            has_data = False
            
            for col in range(1, last_col + 1):
                header = headers[col-1]
                if header == "":  # Skip empty headers
                    continue
                    
                cell = sheet.range(row, col)
                value = cell.value
                
                # Clean the value
                cleaned_value = clean_value(value)
                
                # Convert date if needed
                if col in date_columns and cleaned_value is not None:
                    if isinstance(cleaned_value, str):
                        cleaned_value = parse_date(cleaned_value)
                    elif isinstance(cleaned_value, (datetime, date)):
                        cleaned_value = cleaned_value.strftime("%Y-%m-%d")
                
                if cleaned_value is not None:
                    row_data[header] = cleaned_value
                    has_data = True
            
            # Only add row if it has data
            if has_data:
                row_data['UID'] = len(data) + 1  # 1-based index
                data.append(row_data)
        
        print(f"Processed {len(data)} rows of data")
        
        # Create output filename
        base_name = os.path.splitext(os.path.basename(excel_path))[0]
        output_filename = f"{base_name}.json"
        output_path = os.path.join(output_dir, output_filename)
        
        # Save as JSON with proper formatting
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        
        print(f"Successfully converted to {output_path}")
        if data:
            print("Sample data:")
            print(json.dumps(data[0], indent=2, ensure_ascii=False))
        else:
            print("No data found in the file.")
            
        return output_path
        
    except Exception as e:
        print(f"Error processing {os.path.basename(excel_path)}: {str(e)}")
        traceback.print_exc()
        return None
        
    finally:
        # Clean up
        if 'wb' in locals():
            wb.close()
        if app is not None:
            app.quit()

def convert_two_excels_to_json(company_statement: str, bank_statement: str, output_dir: str):
    """Convert two Excel files to JSON using the same process as convert_excel_to_json.

    Args:
        company_statement: Path to the company statement Excel file (.xlsx/.xls).
        bank_statement: Path to the bank statement Excel file (.xlsx/.xls).
        output_dir: Directory where the JSON files will be saved.

    Returns:
        A single comma-separated string: "<company_json_path>,<bank_json_path>".
        If a conversion fails, the corresponding segment will be empty.
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    company_json = convert_excel_to_json(company_statement, output_dir)
    bank_json = convert_excel_to_json(bank_statement, output_dir)
    # Return as a single comma-separated string, using empty string for None
    return f"{company_json or ''},{bank_json or ''}"

def convert_two_excels_to_json_uipath(company_statement: str, bank_statement: str, output_dir: str) -> str:
    """UiPath-friendly wrapper for converting two Excel files to JSON.

    Same arguments and return as convert_two_excels_to_json, but:
    - Suppresses console output (prints) to avoid host capture issues
    - Ensures output directory exists
    - Returns a simple string or 'ERROR: ...' on failure
    """
    # Coerce inputs to strings defensively (UiPath may pass objects)
    try:
        company_statement = str(company_statement) if company_statement is not None else ""
        bank_statement = str(bank_statement) if bank_statement is not None else ""
        output_dir = str(output_dir) if output_dir is not None else ""
        if not output_dir:
            return "ERROR: output_dir is required"
        os.makedirs(output_dir, exist_ok=True)

        # Suppress prints from inner functions
        import builtins
        _orig_print = builtins.print
        try:
            builtins.print = lambda *a, **k: None
            company_json = convert_excel_to_json(company_statement, output_dir)
            bank_json = convert_excel_to_json(bank_statement, output_dir)
        finally:
            builtins.print = _orig_print

        return f"{company_json or ''},{bank_json or ''}"
    except Exception as e:
        return f"ERROR: {e}"

def main():
    # Define directories
    # test_dataset_dir = os.path.join(os.path.dirname(__file__), 'TestDataset')
    test_dataset_dir = r"D:\PlayWright Extractor\Downloads"
    output_dir = os.path.join(test_dataset_dir, 'json_output')
    
    # Create output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    print(f"Input directory: {test_dataset_dir}")
    print(f"Output directory: {output_dir}")
    
    # Process all Excel files in TestDataset
    processed_files = 0
    for file in sorted(os.listdir(test_dataset_dir)):
        if file.lower().endswith(('.xlsx', '.xls')) and not file.startswith('~$'):  # Skip temp files
            excel_path = os.path.join(test_dataset_dir, file)
            if convert_excel_to_json(excel_path, output_dir):
                processed_files += 1
    
    print(f"\nProcessing complete. Converted {processed_files} files to JSON.")

if __name__ == "__main__":
    main()
