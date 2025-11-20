import re
from playwright.sync_api import Playwright, sync_playwright, expect
import functions
from datetime import datetime
from dateutil.relativedelta import relativedelta
import requests
import pandas as pd
from dotenv import load_dotenv
import os
import MatchStatement_Optimized as MatchStatement
from email_reply import reply_to_trigger_email
from pathlib import Path
from unified_reconciliation import reconcile_unified
from unified_reconciliation import reconcile_unified_uipath
import convert_with_xlwings


def run_RaasPlus(
    playwright: Playwright,
    save_path,
    reconciliation_save_path,
    website_url=os.getenv("WEBSITE_URL"),
    username=os.getenv("WEBSITE_USERNAME"),
    password=os.getenv("PASSWORD"),
    accountName=os.getenv("accountName"),
    pingback_url=None,
    payload=None,
    webhook_url=None
) -> None:
    # Input JSON files
    # Old (fabricated dataset):
    # base = Path(__file__).parent / "fabricated_dataset"
    # bank_json = base / "bank_transactions.json"
    # company_json = base / "company_statements.json"

    # New (previous alt): use aimanpdc/pdc_aiman dataset
    # base = Path(__file__).parent / "aimanpdc" / "pdc_aiman"
    # bank_json = base / "Process Bank Transactions 20250822.json"
    # company_json = base / "Reconciliation Statements 20250822.json"

    # Active: use aimanpdc/upmdatabanyak dataset
    # base = Path(__file__).parent / "aimanpdc" / "upmdatabanyak"
    # bank_json = base / "DBKK_Process Bank Transactions 20250827.json"
    # company_json = base / "Reconciliation Statements 20250828.json"
    # company_json = base / "DBKK_Reconciliation Statements 20250827.json"

    # base = Path(__file__).parent / "fabricated_dataset"
    # bank_json = base / "all_algorithms_bank.json"
    # company_json = base / "all_algorithms_company.json"

    # bank_json = Path(os.path.join(r"D:\PlayWright Extractor\Downloads\json_output", f"{save_path}.json"))
    # print(bank_json)
    # company_json = Path(os.path.join(r"D:\PlayWright Extractor\Downloads\json_output", f"{reconciliation_save_path}.json"))
    # print(company_json)

    bank_json, company_json = convert_with_xlwings.convert_two_excels_to_json(
        company_statement=reconciliation_save_path,
        bank_statement=save_path,
        output_dir=os.path.join(r"Downloads\json_output")
    ).split(",")
    print(bank_json)
    print(company_json)

    verify_bank_json = Path(bank_json)
    verify_company_json = Path(company_json)
    
    # bank_json = Path(convert_with_xlwings.convert_excel_to_json(
    #     excel_path=save_path,
    #     output_dir=bank_output_path
    # ))
    # company_json = Path(convert_with_xlwings.convert_excel_to_json(
    #     excel_path=reconciliation_save_path,
    #     output_dir=company_output_path
    # ))

    # Optional: set an explicit output path. Leave empty string to use timestamped default
    # out_xlsx = str(Path("matching_results") / "fabricated_run.xlsx")
    out_xlsx = ""

    # Toggles for this run
    enable_ai = False  # True
    enable_group_matching = False  # Set False to disable group matching

    if not verify_bank_json.exists():
        raise FileNotFoundError(f"Bank JSON not found: {bank_json}")
    if not verify_company_json.exists():
        raise FileNotFoundError(f"Company JSON not found: {company_json}")

    # Run reconciliation and print the resulting Excel path
    bank_name = "MBB02"  # set to "MBB01" for Bulk EFT by default
    # Optional flags to control the Bulk EFT matcher
    enable_bulk_eft = None  # True/False to explicitly enable/disable
    bulk_eft_allow_any_bank = None  # True to allow Bulk EFT for non-MBB01 banks
    excel_path = reconcile_unified(
        str(bank_json),
        str(company_json),
        out_xlsx,
        enable_ai,
        enable_group_matching,
        bank_name,
        enable_bulk_eft,
        bulk_eft_allow_any_bank,
    )

    functions.log_message(webhook_url, f"Reconciliation completed. Excel saved to:\n{excel_path}")

    reply_to_trigger_email("RAAS+ completed successfully.")

    MatchStatement.run_matching_process(
        playwright,
        matchresultpath=excel_path,
        website_url=website_url,
        username=username,
        password=password,
        accountName=accountName,
        pingback_url=pingback_url,
        payload=payload,
        webhook_url=webhook_url
    )

# def run_RaasPlus(
#     playwright: Playwright,
#     matchresultpath,
#     website_url=os.getenv("WEBSITE_URL"),
#     username=os.getenv("WEBSITE_USERNAME"),
#     password=os.getenv("PASSWORD"),
#     accountName=os.getenv("accountName"),
#     pingback_url=None,
#     payload=None,
#     webhook_url=None
# ):
#     reply_to_trigger_email("RAAS+ completed successfully.")
#     MatchStatement.run_match_process(
#         playwright,
#         matchresultpath=matchresultpath,
#         website_url=website_url,
#         username=username,
#         password=password,
#         accountName=accountName,
#         pingback_url=pingback_url,
#         payload=payload,
#         webhook_url=webhook_url
#     )

if __name__ == "__main__":
    with sync_playwright() as playwright:
        run_RaasPlus(
                playwright = playwright,
                save_path="Downloads\Process Bank Transactions 20251029.xlsx",
                reconciliation_save_path="Downloads\Reconciliation Statements 20251029.xlsx",
                website_url=os.getenv("WEBSITE_URL"),
                username=os.getenv("WEBSITE_USERNAME"),
                password=os.getenv("PASSWORD"),
                pingback_url=None,
                payload=None,
                webhook_url=None
            )
