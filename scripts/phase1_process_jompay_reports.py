import json
import sys
from dataclasses import dataclass
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd


"""
Phase 1: Process JomPAY daily transaction reports.

For each Excel file in the input folder:
- Detect the transaction table (header row contains columns like 'JomPAY Ref No').
- Group transactions by calendar date derived from 'Trx Datetime'.
- Filter rows where 'Debiting Account' == 'Credit Card Account' and
  'Payer Bank Name' == 'CIMB Bank' (case-insensitive, trimmed).
- From the filtered rows, collect the list of 'JomPAY Ref No' and compute
  total_amount = sum(Amount - Fees) per date.
- Save results as JSON in the output folder (one JSON file per input Excel).

Usage:
    python scripts/phase1_process_jompay_reports.py \
        --input-folder daily_report_folder \
        --output-folder json

Output JSON structure (per input file):
{
  "file": "daily_transaction_report.xlsx",
  "generated_at": "2025-10-10T14:45:00Z",
  "groups": [
    {
      "date": "2025-07-02",
      "jompay_ref_nos": ["C8JQQJI3", "C8J9EHQ8"],
      "total_amount": 189.41,
      "count": 2
    }
  ]
}
"""


@dataclass
class ColumnMap:
    jompay_ref: str
    amount: str
    fees: str
    debiting_account: str
    payer_bank_name: str
    trx_datetime: str


EXPECTED_COL_KEYS = ColumnMap(
    jompay_ref="JomPAY Ref No",
    amount="Amount",
    fees="Fees",
    debiting_account="Debiting Account",
    payer_bank_name="Payer Bank Name",
    trx_datetime="Trx Datetime",
)


def _normalize(s: object) -> str:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return str(s).strip()


def _lc(s: object) -> str:
    return _normalize(s).lower()


def detect_header_row(path: Path, max_scan_rows: int = 50) -> Tuple[int, List[str]]:
    """Return (header_row_index, header_values).

    Scans the first `max_scan_rows` rows for a row that looks like the
    transaction header (contains 'JomPAY' and 'Amount').
    """
    df = pd.read_excel(path, header=None, dtype=object, engine="openpyxl")
    scan_rows = min(max_scan_rows, len(df))
    for i in range(scan_rows):
        row = [_normalize(x) for x in df.iloc[i].tolist()]
        low = [_lc(x) for x in row]
        if any("jompay" in x for x in low) and any("amount" in x for x in low):
            # Additional sanity: ensure we also see either 'payer' or 'debit'
            if any("payer" in x for x in low) or any("debit" in x for x in low):
                # Trim trailing blank cells
                while row and row[-1] == "":
                    row.pop()
                return i, row
    raise RuntimeError(
        f"Could not detect transaction header row in {path.name}. "
        "Ensure the sheet contains a row with 'JomPAY Ref No' and 'Amount'."
    )


def build_column_mapping(raw_headers: List[str]) -> Dict[str, str]:
    """Map canonical keys to actual header names in the file.

    Performs case-insensitive, contains-based matching to tolerate minor
    naming variations like 'Payer Bank Na' (truncated).
    """
    headers = [_normalize(h) for h in raw_headers]
    lowered = [h.lower() for h in headers]

    def find_contains(*needles: str) -> Optional[str]:
        for idx, h in enumerate(lowered):
            if all(n in h for n in needles):
                return headers[idx]
        return None

    mapping = {
        "jompay_ref": find_contains("jompay", "ref"),
        "amount": find_contains("amount"),
        "fees": find_contains("fee"),
        # Accept 'debiting account' or truncated like 'biting account'
        "debiting_account": find_contains("biting", "account")
        or find_contains("debit", "account"),
        "payer_bank_name": find_contains("payer", "bank"),
        # 'trx datetime' or anything with 'trx' and 'date'
        "trx_datetime": find_contains("trx", "date") or find_contains("date", "time"),
    }

    missing = [k for k, v in mapping.items() if not v]
    if missing:
        raise RuntimeError(
            "Missing required columns: " + ", ".join(missing) + f". Found headers: {headers}"
        )
    return mapping


def parse_date_from_cell(value: object) -> Optional[date]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    # Try Excel serial date first if plausible
    if isinstance(value, (int, float)):
        # Heuristic: Excel serial dates are typically between 10_000 and 60_000
        if 10000 < float(value) < 60000:
            try:
                return pd.to_datetime(value, unit="D", origin="1899-12-30").date()
            except Exception:
                pass
        # Otherwise treat as integer-like string (e.g., 20250702094533)
        s = str(int(value))
        digits = "".join(ch for ch in s if ch.isdigit())
        if len(digits) >= 8:
            try:
                return datetime.strptime(digits[:8], "%Y%m%d").date()
            except Exception:
                pass
    # String path
    s = _normalize(value)
    digits = "".join(ch for ch in s if ch.isdigit())
    if len(digits) >= 8:
        try:
            return datetime.strptime(digits[:8], "%Y%m%d").date()
        except Exception:
            pass
    # Fallback to pandas
    try:
        return pd.to_datetime(s).date()
    except Exception:
        return None


def to_number(x: object) -> float:
    s = _normalize(x)
    if s == "":
        return 0.0
    # Remove commas and currency symbols if any
    s = s.replace(",", "")
    s = s.replace("RM", "").replace("$", "")
    try:
        return float(s)
    except Exception:
        try:
            return float(pd.to_numeric(s, errors="coerce") or 0)
        except Exception:
            return 0.0


def process_file_df(path: Path) -> pd.DataFrame:
    header_row, header_values = detect_header_row(path)
    mapping = build_column_mapping(header_values)

    df = pd.read_excel(
        path,
        header=header_row,
        dtype=object,
        engine="openpyxl",
    )

    # Normalize and derive fields
    df["__date"] = df[mapping["trx_datetime"]].map(parse_date_from_cell)
    df["__debiting"] = df[mapping["debiting_account"]].map(lambda x: _lc(x))
    df["__payer_bank"] = df[mapping["payer_bank_name"]].map(lambda x: _lc(x))
    df["__amount"] = df[mapping["amount"]].map(to_number)
    df["__fees"] = df[mapping["fees"]].map(to_number)
    df["__net"] = df["__amount"] - df["__fees"]

    # Filter per requirements
    filtered = df[
        (df["__debiting"].str.contains("credit card account", na=False))
        & (df["__payer_bank"].str.fullmatch(r"\s*cimb\s*bank\s*", case=False, na=False))
        & df["__date"].notna()
    ].copy()

    # Add canonical copies of key columns for consistent JSON keys
    filtered["jompay_ref_no"] = filtered[mapping["jompay_ref"]].map(_normalize)
    filtered["amount"] = filtered[mapping["amount"]].map(to_number)
    filtered["fees"] = filtered[mapping["fees"]].map(to_number)
    filtered["debiting_account"] = filtered[mapping["debiting_account"]].map(_normalize)
    filtered["payer_bank_name"] = filtered[mapping["payer_bank_name"]].map(_normalize)
    filtered["trx_datetime"] = filtered[mapping["trx_datetime"]].map(_normalize)
    filtered["source_file"] = path.name

    # Return only filtered df with derived fields present
    return filtered


def save_json_consolidated(data: Dict, out_dir: Path, filename: str = "phase1_jompay_consolidated.json") -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return out_path


def main(argv: List[str]) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Phase 1: Process JomPAY daily transaction reports")
    parser.add_argument("--input-folder", required=True, help="Folder containing daily report Excel files")
    parser.add_argument(
        "--output-folder",
        default="json",
        help="Folder to write JSON outputs (default: json)",
    )
    args = parser.parse_args(argv)

    in_dir = Path(args.input_folder)
    out_dir = Path(args.output_folder)
    if not in_dir.exists() or not in_dir.is_dir():
        print(f"Input folder not found: {in_dir}", file=sys.stderr)
        return 2

    excel_files = [
        p
        for p in in_dir.iterdir()
        if p.suffix.lower() in {".xlsx", ".xls"} and not p.name.startswith("~$")
    ]
    if not excel_files:
        print(f"No Excel files found in {in_dir}")
        return 0

    all_rows: List[pd.DataFrame] = []
    for f in sorted(excel_files):
        try:
            df_f = process_file_df(f)
            if not df_f.empty:
                all_rows.append(df_f)
            print(f"Processed {f.name}: {len(df_f)} filtered rows")
        except Exception as e:
            print(f"ERROR processing {f.name}: {e}", file=sys.stderr)

    if not all_rows:
        consolidated = {
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "input_folder": str(in_dir),
            "file_count": len(excel_files),
            "row_count": 0,
            "groups": [],
        }
        out_path = save_json_consolidated(consolidated, out_dir)
        print(f"No matching rows. Wrote {out_path}")
        return 0

    all_df = pd.concat(all_rows, ignore_index=True)

    def row_to_original_dict(row: pd.Series) -> Dict[str, object]:
        d = {}
        for k, v in row.items():
            if k.startswith("__"):
                continue
            if k in {
                "jompay_ref_no",
                "amount",
                "fees",
                "debiting_account",
                "payer_bank_name",
                "trx_datetime",
                "source_file",
                "net_amount",
            }:
                # we will add canonical copies separately
                continue
            if pd.isna(v):
                continue
            d[str(k)] = v
        return d

    # Prepare rows with canonical keys
    all_df = all_df.copy()
    all_df["net_amount"] = all_df["__net"].map(lambda x: float(round(float(x or 0), 2)))

    groups = []
    for d, g in all_df.groupby("__date"):
        jrefs = (
            g["jompay_ref_no"].dropna().map(_normalize).replace("", pd.NA).dropna().astype(str).tolist()
        )
        # Aggregates requested
        total_amount = float(round(g["amount"].sum(), 2))
        total_fees = float(round(g["fees"].sum(), 2))
        total_net_amount = float(round(g["net_amount"].sum(), 2))
        groups.append(
            {
                "date": d.isoformat(),
                "jompay_ref_nos": jrefs,
                "total_amount": total_amount,
                "total_fees": total_fees,
                "total_net_amount": total_net_amount,
                "count": int(len(g)),
            }
        )

    files_list = [p.name for p in sorted(excel_files)]
    consolidated = {
        "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
        "input_folder": str(in_dir),
        "file": files_list[0] if len(files_list) == 1 else "multiple",
        "files": files_list,
        "file_count": len(files_list),
        "row_count": int(len(all_df)),
        "groups": groups,
    }
    out_path = save_json_consolidated(consolidated, out_dir)
    print(f"Wrote consolidated JSON -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
