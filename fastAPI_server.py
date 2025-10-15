import asyncio
from fastapi import FastAPI, Request
from concurrent.futures import ThreadPoolExecutor
from playwright.sync_api import sync_playwright
from MatchStatement import run_match_process, failed_entries
from ExtractReconcileStatement import run_extract_reconcile
from CAMatchExtract import CAMatchExtract
from AddStatement import run_add_statement

app = FastAPI()
executor = ThreadPoolExecutor()

def run_match_task(data):
    with sync_playwright() as playwright:
        run_match_process(
            playwright,
            data.get("website_url"),
            data.get("username"),
            data.get("password"),
            data.get("accountName"),
            data.get("matchresultpath"),
            data.get("pingback_url"),
            data.get("payload"),
            data.get("webhook_url"),
        )

def run_reconcile_task(data):
    with sync_playwright() as playwright:
        return run_extract_reconcile(
            playwright,
            data.get("website_url"),
            data.get("username"),
            data.get("password"),
            data.get("accountName"),
            data.get("save_path"),
            data.get("pingback_url"),
            data.get("payload"),
            data.get("webhook_url"),
        )

def run_ca_task(data):
    with sync_playwright() as playwright:
        return CAMatchExtract(
            playwright,
            data.get("website_url"),
            data.get("username"),
            data.get("password"),
            data.get("accountName"),
            data.get("save_path"),
            data.get("CAMatchOutputFile"),
            data.get("allowed_types"),
            data.get("pingback_url"),
            data.get("payload"),
            data.get("webhook_url"),
        )

def run_add_statement_task(data):
    with sync_playwright() as playwright:
        run_add_statement(playwright,
                           inputFile=data.get("inputFile"),
                             matchFile=data.get("matchFile")
                             )

@app.post("/run/match")
async def run_match(request: Request):
    data = await request.json()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, run_match_task, data)
    return result

@app.get("/failed-entries")
async def get_failed_entries():
    return failed_entries

@app.post("/run/reconcile")
async def run_reconcile(request: Request):
    data = await request.json()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, run_reconcile_task, data)
    return result

@app.post("/run/camatch")
async def run_ca(request: Request):
    data = await request.json()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(executor, run_ca_task, data)
    return result

@app.post("/run/addstatement")
async def run_addstatement(request: Request):
    data = await request.json()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(executor, run_add_statement_task, data)
    return {"status": "accepted"}