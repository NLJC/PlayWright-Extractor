import re
import json
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd


def _safe_float(s: Optional[str]) -> float:
    try:
        return float(str(s).replace(",", "").strip())
    except Exception:
        return 0.0


def parse_cimb02_txt(path: Path) -> pd.DataFrame:
    """Parse CIMB 'cim02' statement using fixed column widths.

    Widths: 14, 6, 8, 4, 15, 4, 8, 13, 1, 13, 1, 6, 35, 12, 1, 20, 20, 20
    """
    widths = [14, 6, 8, 4, 15, 4, 8, 13, 1, 13, 1, 6, 35, 12, 1, 20, 20, 20]
    total = sum(widths)
    lines = Path(path).read_text(encoding="utf-8", errors="ignore").splitlines()
    # Explicit per-spec: first 6 lines are headers; skip them
    if len(lines) >= 6:
        lines = lines[6:]
    data: List[dict] = []

    def slice_line(s: str) -> List[str]:
        s = s.rstrip("\n\r")
        if len(s) < total:
            s = s + " " * (total - len(s))
        out = []
        i = 0
        for w in widths:
            out.append(s[i:i+w])
            i += w
        return out

    # Remaining lines are the fixed-width table
    for raw in lines:
        parts = slice_line(raw)
        if len(parts) < 18:
            continue
        acct = parts[0].strip()
        record = parts[1].strip()
        ddmmyyyy = parts[2].strip()
        if not (acct and record and re.fullmatch(r"\d{8}", ddmmyyyy or "")):
            continue
        code = parts[3].strip()
        desc = parts[4].rstrip()
        orig = parts[5].strip()
        document = parts[6].strip()
        amt_s = parts[7].strip()
        amt_dc = parts[8].strip()
        bal_s = parts[9].strip()
        bal_dc = parts[10].strip()
        time6 = parts[11].strip()
        cust_ref = parts[12].strip()
        filler = parts[13].strip()
        filler_flag = parts[14].strip()
        recip_ref = parts[15].strip()
        other_detail = parts[16].strip()
        sender_name = parts[17].strip()

        # Convert fields
        try:
            tran_date = pd.to_datetime(ddmmyyyy, format="%d%m%Y").strftime("%Y-%m-%d")
        except Exception:
            tran_date = None
        amount = _safe_float(amt_s)
        balance = _safe_float(bal_s)
        receipt = amount if (amt_dc.upper() == "C") else 0.0
        disb = amount if (amt_dc.upper() == "D") else 0.0

        ext_tran_id = (orig + document).strip() if (orig or document) else None
        if ext_tran_id and not re.fullmatch(r"\d{8,12}", ext_tran_id):
            ext_tran_id = None

        # Ext Ref from reference fields
        ext_ref = None
        for src in (cust_ref, recip_ref, other_detail):
            if not src:
                continue
            m = re.search(r"DBKK\s*:?\s*(\d{8,20})", src, flags=re.IGNORECASE)
            if m:
                ext_ref = m.group(1)
                break

        data.append({
            "Account Number": acct or None,
            "Record No": record or None,
            "Tran. Date": tran_date,
            "Tran Code": code or None,
            "Tran. Desc": desc.strip() or None,
            "Receipt": receipt,
            "Disbursement": disb,
            "Amount DC": amt_dc or None,
            "Running Balance": balance,
            "Balance DC": bal_dc or None,
            "Tran Time": time6 or None,
            "Ext. Ref. Nbr.": ext_ref,
            "Ext. Tran. ID": ext_tran_id,
            "Customer Reference": cust_ref or None,
            "Recipient Reference": recip_ref or None,
            "Other Payment Detail": other_detail or None,
            "Sender Name": sender_name or None,
        })

    return pd.DataFrame(data)


def merge_into_excel(
    txt_df: pd.DataFrame,
    xlsx_path: Path,
    out_path: Path,
    show_diff: bool = False,
    diff_limit: int = 20,
    diff_out: Optional[Path] = None,
) -> Path:
    base = pd.read_excel(xlsx_path, engine="openpyxl")

    # Normalize common fields for joining
    def key_desc(s: pd.Series) -> pd.Series:
        return s.astype(str).str.strip().str.upper().str.replace(r"\s+", " ", regex=True)

    base_cols = list(base.columns)
    # Add expected new columns if missing
    new_cols = [
        "Account Number",
        "Record No",
        "Tran Code",
        "Amount DC",
        "Running Balance",
        "Balance DC",
        "Tran Time",
        "Customer Reference",
        "Recipient Reference",
        "Other Payment Detail",
        "Sender Name",
    ]
    for c in new_cols:
        if c not in base.columns:
            base[c] = pd.NA

    # Snapshot BEFORE population (after columns exist)
    pre = base.copy(deep=True)

    # Primary join on Ext. Ref. Nbr.
    left = base.copy()
    right = txt_df.copy()
    left["__k_ref"] = left.get("Ext. Ref. Nbr.", pd.Series([pd.NA] * len(left))).astype(str).str.strip()
    right["__k_ref"] = right.get("Ext. Ref. Nbr.", pd.Series([pd.NA] * len(right))).astype(str).str.strip()

    merged = left.merge(
        right[
            [
                "__k_ref",
                "Account Number",
                "Record No",
                "Tran Code",
                "Amount DC",
                "Running Balance",
                "Balance DC",
                "Tran Time",
                "Customer Reference",
                "Recipient Reference",
                "Other Payment Detail",
                "Sender Name",
                "Ext. Tran. ID",
            ]
        ],
        on="__k_ref",
        how="left",
        suffixes=("", "_txt"),
        indicator=True,
    )

    # Coalesce values brought in via primary key match (fill base columns from *_txt where empty)
    for c in [
        "Account Number",
        "Record No",
        "Tran Code",
        "Amount DC",
        "Running Balance",
        "Balance DC",
        "Tran Time",
        "Customer Reference",
        "Recipient Reference",
        "Other Payment Detail",
        "Sender Name",
        "Ext. Tran. ID",
    ]:
        col_txt = f"{c}_txt"
        if c in merged.columns and col_txt in merged.columns:
            merged[c] = merged[c].where(merged[c].notna(), merged[col_txt])

    # Fallback match for rows not matched by ref: date + amount + desc
    unmatched_mask = merged["_merge"] != "both"
    if unmatched_mask.any():
        unmatched_rows = merged[unmatched_mask].copy()
        matched_rows = merged[~unmatched_mask].copy()

        # Build fallback keys
        def norm_amounts(df: pd.DataFrame) -> pd.Series:
            r = pd.to_numeric(df.get("Receipt", 0), errors="coerce").fillna(0).round(2)
            d = pd.to_numeric(df.get("Disbursement", 0), errors="coerce").fillna(0).round(2)
            return (r.astype(str) + "|" + d.astype(str))

        excel_un = unmatched_rows.copy()
        excel_un["__k_fallback"] = (
            pd.to_datetime(excel_un.get("Tran. Date", pd.NaT), errors="coerce").dt.strftime("%Y-%m-%d")
            + "|"
            + norm_amounts(excel_un)
            + "|"
            + key_desc(excel_un.get("Tran. Desc", pd.Series([pd.NA] * len(excel_un))))
        )

        txt_df2 = txt_df.copy()
        txt_df2["__k_fallback"] = (
            pd.to_datetime(txt_df2.get("Tran. Date", pd.NaT), errors="coerce").dt.strftime("%Y-%m-%d")
            + "|"
            + (pd.to_numeric(txt_df2.get("Receipt", 0), errors="coerce").fillna(0).round(2).astype(str)
               + "|"
               + pd.to_numeric(txt_df2.get("Disbursement", 0), errors="coerce").fillna(0).round(2).astype(str))
            + "|"
            + key_desc(txt_df2.get("Tran. Desc", pd.Series([pd.NA] * len(txt_df2))))
        )

        fb = excel_un.merge(
            txt_df2[[
                "__k_fallback",
                "Account Number","Record No","Tran Code","Amount DC","Running Balance","Balance DC","Tran Time",
                "Customer Reference","Recipient Reference","Other Payment Detail",
                "Sender Name","Ext. Tran. ID","Ext. Ref. Nbr."]],
            on="__k_fallback",
            how="left",
            suffixes=("", "_txt2"),
        )

        # Coalesce new info into columns where missing
        for c in [
            "Account Number","Record No","Tran Code","Amount DC","Running Balance","Balance DC","Tran Time",
            "Customer Reference","Recipient Reference","Other Payment Detail",
            "Sender Name","Ext. Tran. ID"
        ]:
            base_col = c
            # prefer existing merged values; fill with fallback
            merged.loc[unmatched_mask, base_col] = merged.loc[unmatched_mask, base_col].fillna(fb[c])
        # Also populate Ext. Ref. Nbr. if missing
        merged.loc[unmatched_mask, "Ext. Ref. Nbr."] = merged.loc[unmatched_mask, "Ext. Ref. Nbr."].fillna(fb["Ext. Ref. Nbr."])

    # Drop helper columns
    drop_cols = [c for c in ["__k_ref", "_merge", "Tail"] if c in merged.columns]
    # Also drop any helper right-side columns left from merge
    drop_cols += [c for c in merged.columns if c.endswith("_txt") or c.endswith("_txt2")]
    if drop_cols:
        merged.drop(columns=drop_cols, inplace=True, errors='ignore')

    # Save out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    merged.to_excel(out_path, index=False)

    # Optional diff report
    if show_diff or diff_out is not None:
        common_cols = [c for c in merged.columns if c in pre.columns]
        def norm(s: pd.Series) -> pd.Series:
            return s.where(~s.isna(), other="__NA__").astype(str)

        changes = {}
        for c in common_cols:
            a = norm(pre[c])
            b = norm(merged[c])
            m = a != b
            if m.any():
                changes[c] = m
        report_rows = []
        if changes:
            any_change = pd.DataFrame(changes).any(axis=1)
            idxs = list(merged[any_change].index)
            key_cols = [k for k in ["Ext. Ref. Nbr.", "Ext. Tran. ID", "Tran. Date", "Tran. Desc"] if k in merged.columns]
            for i in idxs:
                changed_cols = [c for c, m in changes.items() if bool(m.iloc[i])]
                r = {"row_index": int(i), "changed_cols": changed_cols}
                for k in key_cols:
                    r[k] = merged.at[i, k]
                for c in changed_cols:
                    r[f"old::{c}"] = pre.at[i, c]
                    r[f"new::{c}"] = merged.at[i, c]
                report_rows.append(r)
        if show_diff:
            print(f"Modified rows: {len(report_rows)}")
            for r in report_rows[: max(1, int(diff_limit))]:
                keys = ", ".join([f"{k}={r.get(k)}" for k in ["Ext. Ref. Nbr.", "Ext. Tran. ID"] if k in r])
                print(f"- Row {r['row_index']} | {keys} | changed: {', '.join(r['changed_cols'])}")
        if diff_out is not None:
            diff_out.parent.mkdir(parents=True, exist_ok=True)
            Path(diff_out).write_text(pd.DataFrame(report_rows).to_json(orient="records", indent=2), encoding="utf-8")

    return out_path


def main():
    import argparse
    ap = argparse.ArgumentParser(description="Merge CIMB cim02 text into Process Bank Transactions Excel by adding missing columns")
    ap.add_argument("--txt", default="og_bank_statement/cim02 jul 2025.txt", help="Path to CIMB cim02 text file")
    ap.add_argument("--xlsx", default="dbkk_dataset/Process Bank Transactions 20251010.xlsx", help="Path to target Excel")
    ap.add_argument("--out", default="dbkk_dataset/Process Bank Transactions 20251010_enriched.xlsx", help="Path to write enriched Excel")
    ap.add_argument("--dump-json", default="", help="Optional path to dump parsed TXT as JSON for inspection")
    ap.add_argument("--show-diff", action="store_true", help="Print summary of modified rows")
    ap.add_argument("--diff-limit", type=int, default=20, help="Max # of modified rows to print")
    ap.add_argument("--diff-out", default="", help="Optional path to save detailed diff JSON report")
    args = ap.parse_args()

    txt_df = parse_cimb02_txt(Path(args.txt))
    if args.dump_json:
        Path(args.dump_json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.dump_json).write_text(txt_df.to_json(orient="records", indent=2), encoding="utf-8")
    out = merge_into_excel(
        txt_df,
        Path(args.xlsx),
        Path(args.out),
        show_diff=bool(args.show_diff),
        diff_limit=int(args.diff_limit or 20),
        diff_out=(Path(args.diff_out) if args.diff_out else None),
    )
    print(f"Enriched Excel written to: {out}")


if __name__ == "__main__":
    main()
