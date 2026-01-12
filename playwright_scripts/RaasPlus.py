import os
from pathlib import Path

from playwright.sync_api import Playwright, expect, sync_playwright

from helper_playwright import functions
from helper_playwright.email_reply import reply_to_trigger_email
from helper_playwright.paths import get_downloads_dir
from Raas_Plus.unified_reconciliation import reconcile_unified, reconcile_unified_uipath
from Raas_Plus import convert_with_xlwings
from . import MatchStatement_Optimized as MatchStatement


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
    webhook_url=None,
    headless=False
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

    # --- AUDIT TRAIL & JOMPAY BRIDGE ---
    # Determine if we are in a specific run folder
    run_dir = get_downloads_dir()
    attachments_dir = run_dir / "attachments"
    intermediates_dir = run_dir / "intermediates"
    outputs_dir = run_dir / "outputs"
    
    # Ensure structure exists (it should if created by email_queue, but good safety)
    if not intermediates_dir.exists():
        intermediates_dir.mkdir(parents=True, exist_ok=True)
    if not outputs_dir.exists():
        outputs_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scan for JomPAY and Credit Card files
    from email_processing.attachment_utils import identify_file_type
    
    jompay_json_override = None
    cc_input_override = None
    
    if attachments_dir.exists():
        # Check for files
        for file_path in attachments_dir.glob("*"):
            if file_path.is_file():
                f_type = identify_file_type(file_path)
                if f_type == "DAILY_REPORT":
                    print(f"Detected JomPAY Daily Report: {file_path.name}")
                    # Trigger Phase 1 script
                    # We can import and run, or subprocess. Subprocess is safer for script isolation but import is cleaner if structure allows.
                    # Given it's a script, let's try subprocess to avoid path issues or import side effects
                    import subprocess
                    import sys
                    
                    script_path = Path(__file__).parent.parent / "scripts" / "phase1_process_jompay_reports.py"
                    processed_json_path = intermediates_dir / "jompay_consolidated.json"
                    
                    try:
                        cmd = [
                            sys.executable, str(script_path),
                            "--input-folder", str(attachments_dir), # Point to where the file is
                            "--output", str(processed_json_path)
                        ]
                        print(f"Running Phase 1 JomPAY processing...")
                        subprocess.run(cmd, check=True, capture_output=True)
                        if processed_json_path.exists():
                            jompay_json_override = str(processed_json_path)
                            print(f"JomPAY JSON generated at: {jompay_json_override}")
                    except Exception as e:
                        print(f"Failed to process JomPAY report: {e}")
                        
                elif f_type == "CREDIT_CARD":
                    print(f"Detected Credit Card File: {file_path.name}")
                    # We set the FOLDER as the override, as the algo looks into the folder
                    cc_input_override = str(attachments_dir)
    
    # -----------------------------------

    output_dir = get_downloads_dir() / "json_output"
    output_dir.mkdir(parents=True, exist_ok=True)

    bank_json, company_json = convert_with_xlwings.convert_two_excels_to_json(
        company_statement=reconciliation_save_path,
        bank_statement=save_path,
        output_dir=str(output_dir)
    ).split(",")
    print(bank_json)
    print(company_json)

    verify_bank_json = Path(bank_json)
    verify_company_json = Path(company_json)
    
    # Output path for the main Excel result
    # We save it to the "outputs" folder if we are in a run structure, otherwise generic
    if (run_dir / "outputs").exists():
        timestamp = os.path.basename(str(run_dir)).split("_")[0] # rudimentary
        out_xlsx = str(run_dir / "outputs" / f"ReconciliationResult.xlsx")
    else:
        out_xlsx = ""

    # Toggles for this run
    enable_ai = False  # True
    enable_group_matching = False  # Set False to disable group matching

    if not verify_bank_json.exists():
        raise FileNotFoundError(f"Bank JSON not found: {bank_json}")
    if not verify_company_json.exists():
        raise FileNotFoundError(f"Company JSON not found: {company_json}")

    # Run reconciliation and print the resulting Excel path
    # Derive bank_name from accountName parameter (e.g., "CIM02", "MBB02", "MBB01")
    bank_name = accountName if accountName else "MBB02"  # fallback to MBB02 if not provided
    # Optional flags to control the Bulk EFT matcher
    enable_bulk_eft = None  # True/False to explicitly enable/disable
    bulk_eft_allow_any_bank = None  # True to allow Bulk EFT for non-MBB01 banks
    
    # Pass overrides to reconcile_unified
    # NOTE: We need to modify reconcile_unified signature or kwargs to accept these if it doesn't already
    # Checking unified_reconciliation.py first would have been ideal, but purely based on context:
    # We will assume we can pass config_overrides dict or similar if supported, 
    # OR we set ENV VARS temporarily which is the Universal way without changing the function signature immediately.
    
    # Strategy: Set ENV VARS for the overrides, as UnifiedConfig.from_env() likely reads them.
    # This avoids changing the function signature of `reconcile_unified`.
    
    env_overrides = {}
    if cc_input_override:
        os.environ["MBB02_CC_INPUT_FOLDER"] = cc_input_override
        env_overrides["MBB02_CC_INPUT_FOLDER"] = cc_input_override
    if jompay_json_override:
        os.environ["JOMPAY_CONSOLIDATED_JSON"] = jompay_json_override
        env_overrides["JOMPAY_CONSOLIDATED_JSON"] = jompay_json_override
        
    # Also set output dirs for visuals/unmatched if in run mode
    if (run_dir / "outputs").exists():
        vis_out = run_dir / "outputs" / "visuals"
        vis_out.mkdir(exist_ok=True)
        os.environ["VIS_OUTPUT_DIR"] = str(vis_out)
        
        unmatched_out = run_dir / "outputs" / "unmatched.json"
        os.environ["SAVE_UNMATCHED_JSON"] = str(unmatched_out)

    try:
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
    finally:
        # Cleanup env vars to avoid polluting next run if process stays alive
        for k in env_overrides:
            os.environ.pop(k, None)
        # We don't pop VIS_OUTPUT_DIR etc as they are less critical, but good practice
        if "VIS_OUTPUT_DIR" in os.environ: os.environ.pop("VIS_OUTPUT_DIR")
        if "SAVE_UNMATCHED_JSON" in os.environ: os.environ.pop("SAVE_UNMATCHED_JSON")

    functions.log_message(webhook_url, f"Reconciliation completed. Excel saved to:\n{excel_path}")

    # Note: Email with failed_entries.xlsx attachment will be sent after MatchStatement completes

    MatchStatement.run_matching_process(
        playwright,
        matchresultpath=excel_path,
        website_url=website_url,
        username=username,
        password=password,
        accountName=accountName,
        pingback_url=pingback_url,
        payload=payload,
        webhook_url=webhook_url,
        headless=headless
    )

    # Email notification is handled by MatchStatement (includes failed_entries.xlsx if any failures)

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
                save_path=r"Downloads\Process Bank Transactions 20251029.xlsx",
                reconciliation_save_path=r"Downloads\Reconciliation Statements 20251029.xlsx",
                website_url=os.getenv("WEBSITE_URL"),
                username=os.getenv("WEBSITE_USERNAME"),
                password=os.getenv("PASSWORD"),
                pingback_url=None,
                payload=None,
                webhook_url=None
            )
