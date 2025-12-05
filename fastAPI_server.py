import asyncio
import traceback
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from datetime import datetime

# Import optimized scripts
from playwright_scripts.CA_Match_Process_Optimized import process_bank_transactions
from playwright_scripts.ExtractReconcileStatement_Optimized import extract_reconciliation_statements
from playwright_scripts.MatchStatement_Optimized import process_match_statement
from helper_playwright.AddStatement import run_add_statement
from helper_playwright.email_reply import reply_to_trigger_email

# Import infrastructure
from logger import logger
from config import Config

app = FastAPI(title="RPA Playwright Extractor", version="2.0.0")
executor = ThreadPoolExecutor(max_workers=3)

# In-memory task tracking
active_tasks = {}

def run_with_retry(task_func, task_name: str, max_retries: int = 3, **kwargs):
    """
    Executes a task with retry logic.
    If all retries fail, sends an email notification.
    """
    attempt = 0
    errors = []
    
    logger.info(f"Starting task: {task_name}")
    
    while attempt < max_retries:
        try:
            attempt += 1
            logger.info(f"Attempt {attempt}/{max_retries} for {task_name}")
            
            # Execute the task
            result = task_func(**kwargs)
            
            logger.info(f"Task {task_name} completed successfully on attempt {attempt}")
            return {"status": "success", "data": result, "attempts": attempt}
            
        except Exception as e:
            error_msg = f"Attempt {attempt} failed: {str(e)}"
            logger.error(error_msg)
            logger.error(traceback.format_exc())
            errors.append(error_msg)
            
            if attempt < max_retries:
                import time
                time.sleep(5)  # Wait before retry
    
    # If we get here, all retries failed
    logger.critical(f"Task {task_name} failed after {max_retries} attempts.")
    
    # Send failure email
    try:
        error_summary = "\n".join(errors)
        email_body = (
            f"❌ RPA Task Failed: {task_name}\n\n"
            f"The task failed after {max_retries} attempts.\n\n"
            f"Error Log:\n{error_summary}\n\n"
            f"Timestamp: {datetime.now().isoformat()}"
        )
        reply_to_trigger_email(email_body)
        logger.info("Failure notification email sent.")
    except Exception as email_err:
        logger.error(f"Failed to send failure email: {email_err}")
        
    return {"status": "failed", "errors": errors}

def run_match_task(data: Dict[str, Any]):
    """Wrapper for CA Match Process"""
    def _task():
        with sync_playwright() as playwright:
            return process_bank_transactions(
                playwright=playwright,
                accountName=data.get("accountName", Config.ACCOUNT_NAME),
                date=data.get("date"), # Expecting date in payload or defaults in script
                amount=data.get("amount", 100.00),
                website_url=data.get("website_url", Config.WEBSITE_URL),
                username=data.get("username", Config.USERNAME),
                password=data.get("password", Config.PASSWORD),
                pingback_url=data.get("pingback_url"),
                payload=data.get("payload"),
                webhook_url=data.get("webhook_url"),
                headless=Config.HEADLESS_MODE
            )
    
    return run_with_retry(_task, "CA_Match_Process")

def run_reconcile_task(data: Dict[str, Any]):
    """Wrapper for Extract Reconciliation Statement"""
    def _task():
        with sync_playwright() as playwright:
            return extract_reconciliation_statements(
                playwright=playwright,
                accountName=data.get("accountName", Config.ACCOUNT_NAME),
                date=data.get("date"),
                amount=data.get("amount"),
                save_path=data.get("save_path"),
                website_url=data.get("website_url", Config.WEBSITE_URL),
                username=data.get("username", Config.USERNAME),
                password=data.get("password", Config.PASSWORD),
                pingback_url=data.get("pingback_url"),
                payload=data.get("payload"),
                webhook_url=data.get("webhook_url"),
                headless=Config.HEADLESS_MODE
            )
            
    return run_with_retry(_task, "Extract_Reconcile_Statement")

def run_ca_match_extract_task(data: Dict[str, Any]):
    """Wrapper for Match Statement (using Optimized version)"""
    def _task():
        with sync_playwright() as playwright:
            return process_match_statement(
                playwright=playwright,
                accountName=data.get("accountName", Config.ACCOUNT_NAME),
                date=data.get("date"),
                amount=data.get("amount"),
                website_url=data.get("website_url", Config.WEBSITE_URL),
                username=data.get("username", Config.USERNAME),
                password=data.get("password", Config.PASSWORD),
                headless=Config.HEADLESS_MODE
            )
            
    return run_with_retry(_task, "Match_Statement_Process")

def run_add_statement_task(data: Dict[str, Any]):
    """Wrapper for Add Statement"""
    def _task():
        with sync_playwright() as playwright:
            run_add_statement(
                playwright,
                inputFile=data.get("inputFile"),
                matchFile=data.get("matchFile")
            )
            
    return run_with_retry(_task, "Add_Statement_Process")

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.get("/status")
async def get_status():
    """Get status of active tasks."""
    return active_tasks

@app.post("/run/match")
async def run_match(request: Request):
    try:
        data = await request.json()
        loop = asyncio.get_running_loop()
        # In a real production app, we'd use a proper task queue (Celery/Redis)
        # For now, we use ThreadPoolExecutor but don't await the result to avoid blocking
        # However, the original code awaited it, so we will keep that behavior for now
        # to ensure we return the result to the caller.
        result = await loop.run_in_executor(executor, run_match_task, data)
        return result
    except Exception as e:
        logger.error(f"API Error in /run/match: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run/reconcile")
async def run_reconcile(request: Request):
    try:
        data = await request.json()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, run_reconcile_task, data)
        return result
    except Exception as e:
        logger.error(f"API Error in /run/reconcile: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run/camatch")
async def run_ca(request: Request):
    try:
        data = await request.json()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, run_ca_match_extract_task, data)
        return result
    except Exception as e:
        logger.error(f"API Error in /run/camatch: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run/addstatement")
async def run_addstatement(request: Request):
    try:
        data = await request.json()
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(executor, run_add_statement_task, data)
        return result
    except Exception as e:
        logger.error(f"API Error in /run/addstatement: {e}")
        raise HTTPException(status_code=500, detail=str(e))
