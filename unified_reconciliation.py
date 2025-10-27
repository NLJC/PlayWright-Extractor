"""
Unified Bank Reconciliation Engine (Standalone Orchestrator)

- Composes the traditional and AI-enhanced reconcilers without inheritance
- Moves ALL AI verification/matching to the end of the pipeline
- Consolidates configuration hyperparameters from both modules, plus experimental/visualization toggles

This module orchestrates:
1) Traditional matching (exact, amount-date, fuzzy, transaction-id, name+amount, reverse CE/GL, group 1:n & n:1, bank charges)
2) AI-enhanced verification and semantic matching at the end only
3) Optional experimental matchers and visualizations (stubs provided; guarded by config flags)

Backwards-compatible assumptions:
- Keeps UID handling and DataFrame preprocessing consistent with existing modules
- Uses existing `enhanced_reconciliation.EnhancedReconciler` for traditional logic
- Uses existing `ai_enhanced_reconciliation.AIEnhancedReconciler` for AI logic

Note: This file does NOT inherit from parent classes. It composes them and controls ordering.
"""

# =============================
# Imports
# =============================
import json
import logging
import time
import requests
from typing import Dict, List, Optional, Tuple, Any, Union, Set, Callable
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from tqdm import tqdm
import pandas as pd
import numpy as np
from fuzzywuzzy import fuzz, process
from collections import defaultdict, Counter
import os
from pathlib import Path
import re
import sys
import io
from itertools import combinations

try:
    from scripts import mbb02_cr_dr_matching as mbb02_cc
except Exception:
    mbb02_cc = None

try:
    from tqdm import tqdm
except Exception:
    def tqdm(it, *args, **kwargs):
        return it

# All reconcilers and dataclasses are implemented within this module.

# Public API for importers
__all__ = [
    'UnifiedConfig', 'UnifiedReconciler', 'reconcile_unified', 'MatchResult'
]

# =============================
# IO Encoding Safety (Windows/UiPath)
# =============================
# Ensure stdout/stderr can emit UTF-8 to avoid 'charmap' codec errors when
# UiPath or other hosts capture Python output containing non-ASCII.
try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    else:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")
except Exception:
    # Best-effort only; never fail module import due to encoding adjustments
    pass

# =============================
# Unified Configuration
# =============================
class UnifiedConfig:
    """
    Consolidated configuration for the unified engine, including:
    - All traditional config values from EnhancedReconciliationConfig
    - All AI-related hyperparameters (verification weights, caching, retries, models)
    - Experimental matcher and visualization toggles

    Defaults follow current behavior of the respective modules to preserve parity.
    """

    # -------- Traditional (from enhanced_reconciliation.py) --------
    LOG_LEVEL: str = 'WARNING'
    LOG_TO_FILE: bool = True

    DATE_FORMAT: str = "%Y-%m-%d"

    AMOUNT_TOLERANCE: float = 0.0
    DATE_TOLERANCE_DAYS: int = 100
    MIN_FUZZY_SCORE: int = 70
    MIN_MATCH_SCORE: float = 0.7

    MAX_GROUP_SIZE: int = 3
    MAX_GROUP_DATE_RANGE: int = 100
    MIN_GROUP_SCORE: int = 60
    MAX_GROUP_AMOUNT_DIFF_PCT: float = 0.0
    MAX_TRANSACTIONS_TO_CONSIDER: int = 50
    MAX_COMBINATIONS_TO_TRY: int = 2000

    AMOUNT_WEIGHT: float = 0.5
    DATE_WEIGHT: float = 0.2
    REF_WEIGHT: float = 0.2
    DESC_WEIGHT: float = 0.1

    OUTPUT_DECIMALS: int = 2
    # General thresholds
    MIN_NONZERO_AMOUNT: float = 0.01
    DEFAULT_DATE_COMPONENT: float = 0.5
    # Reference matching thresholds/scores
    REF_FUZZY_PARTIAL_RATIO_THRESHOLD: int = 90
    REF_EXACT_SCORE: float = 1.0
    REF_PARTIAL_CONTAINS_SCORE: float = 0.9
    REF_LAST6_SCORE: float = 0.8
    REF_FUZZY_SCORE: float = 0.8

    # Field mappings - Bank
    BANK_REF_FIELD: str = "Ext. Ref. Nbr."
    BANK_TXN_ID_FIELD: str = "Ext. Tran. ID"
    BANK_DATE_FIELD: str = "Tran. Date"
    BANK_DESC_FIELD: str = "Tran. Desc"
    BANK_RECEIPT_FIELD: str = "Receipt"
    BANK_DISBURSEMENT_FIELD: str = "Disbursement"

    # Field mappings - Company
    COMPANY_REF_FIELD: str = "Document Ref."
    COMPANY_DATE_FIELD: str = "Doc. Date"
    COMPANY_DESC_FIELD: str = "Description"
    COMPANY_RECEIPT_FIELD: str = "Receipt"
    COMPANY_DISBURSEMENT_FIELD: str = "Disbursement"

    # -------- AI-related (from ai_enhanced_reconciliation.py and memories) --------
    # API
    OPEN_ROUTER_KEY: Optional[str] = None  # picked up from environment if None
    # Preferred list of free models to try in order
    OPENROUTER_MODELS: List[str] = [
        'openai/gpt-oss-20b:free',
        'openai/gpt-oss-120b:free',
        'google/gemma-3n-e2b-it:free',
        'google/gemma-3n-e4b-it:free',
        'google/gemma-2-9b-it:free',
        'google/gemma-3-12b-it:free',
        'google/gemma-3-27b-it:free',
        'qwen/qwen3-4b:free',
        'qwen/qwen3-8b:free',
        'qwen/qwen3-14b:free',
        'qwen/qwen3-235b-a22b:free',
        'meta-llama/llama-4-scout:free',
        'meta-llama/llama-3.3-8b-instruct:free',
        'meta-llama/llama-4-maverick:free',
        'tngtech/deepseek-r1t2-chimera:free',
        'tngtech/deepseek-r1t-chimera:free',
        'deepseek/deepseek-r1-0528:free',
        'deepseek/deepseek-r1:free',
        'microsoft/mai-ds-r1:free',
        'mistralai/mistral-small-3.2-24b-instruct:free',
        'deepseek/deepseek-r1-0528-qwen3-8b:free',
        'cognitivecomputations/dolphin-mistral-24b-venice-edition:free',
        'openai/gpt-oss-20b:free',
        'z-ai/glm-4.5-air:free',
        'tencent/hunyuan-a13b-instruct:free',
    ]

    # OPENROUTER_MODELS: List[str] = [
    #     'openai/gpt-oss-120b',
    #     'google/gemini-2.0-flash-001',
    #    'google/gemma-2-9b-it',
    #    'meta-llama/llama-3.2-3b-instruct'
    # ]

    OPENROUTER_API_URL: str = "https://openrouter.ai/api/v1/chat/completions"
    OPENROUTER_API_KEY_ENV: str = 'OPEN_ROUTER_KEY'
    MAX_TOKENS: int = 5000
    AI_VERIFICATION_BATCH_SIZE: int = 3  # Batch size for AI matching to reduce API calls
    AI_MATCHING_BATCH_SIZE: int = 3     # Batch size for AI matching stage
    VERIFICATION_TIMEOUT: int = 30
    RATE_LIMIT_DELAY: float = 2.0
    MAX_RETRIES: int = 3
    RATE_LIMIT_WAIT: int = 60
    # Advanced async/runtime knobs (not all used directly by current AI class)
    OPENROUTER_CONCURRENCY: int = 3
    OPENROUTER_RATE_LIMIT_QPS: float = 1.5
    # Performance knobs to reduce API usage
    OPENROUTER_TIMEOUT: int = 5   # seconds per request (reduced for faster fallback)
    AI_MAX_API_CALLS: int = 5000   # cap remote calls per run (increased for better coverage)
    AI_SKIP_HIGH_CONFIDENCE_THRESHOLD: float = 0.75  # skip AI if local score >= this (lowered)
    AI_SKIP_LOW_CONFIDENCE_THRESHOLD: float = 0.50   # skip AI if local score <= this (raised)
    AI_CIRCUIT_BREAKER_FAILURES: int = 3  # disable AI after N consecutive failures
    AI_ENABLE_SMART_BATCHING: bool = True  # group similar transactions for batch processing
    AI_CACHE_SIMILAR_THRESHOLD: float = 0.95  # reuse AI results for very similar transactions

    # AI scoring weights (as per memories: 20/20/20/40)
    AI_AMOUNT_WEIGHT: float = 0.2
    AI_DATE_WEIGHT: float = 0.2
    AI_REF_WEIGHT: float = 0.2
    AI_DESC_WEIGHT: float = 0.4

    # AI thresholds and cache
    SEMANTIC_CACHE_SIZE: int = 500
    SEMANTIC_CACHE_TTL: int = 86400
    MATCH_CACHE_SIZE: int = 1000
    AI_MIN_CONFIDENCE: float = 0.70
    AI_SEMANTIC_THRESHOLD: float = 0.70
    AI_MAX_DATE_DIFF: int = 100
    AI_ENABLE_GROUP_MATCHING: bool = True
    # Master toggle for traditional group matching stage (Stage 1)
    ENABLE_GROUP_MATCHING: bool = False
    AI_STRICT_AMOUNT_WHEN_ZERO_TOLERANCE: bool = True
    AI_STRICT_REJECT_CONFIDENCE_CAP: float = 0.49
    MIN_GROUP_SIMILARITY: float = 0.65
    AI_MAX_GROUP_SIZE: int = 3
    MAX_POTENTIAL_GROUP_MATCHES: int = 100

    # AI toggles
    ENABLE_AI: bool = True   # Re-enable AI with improved error handling
    ENABLE_AI_MATCHING: bool = False  # disable Stage 3 by default
    ENABLE_AI_VERIFICATION: bool = True  # keep Stage 4 enabled by default
    # Debug/diagnostics controls for AI verification
    AI_FORCE_REMOTE_VERIFY: bool = True  # when True, bypass skip/caching to force remote calls
    AI_DEBUG_LOG_SKIPS: bool = True       # emit detailed [SKIP] diagnostics for verification
    VERIFY_EXISTING_MATCHES: bool = False  # if True, re-verify high-confidence base matches
    SKIP_AI_FOR_HIGH_CONFIDENCE: bool = True
    ENABLE_CROSS_VALIDATION: bool = True
    STRICT_AMOUNT_MATCHING: bool = True

    # -------- Stricter AI Verification (new) --------
    ENABLE_STRICT_VERIFICATION: bool = False
    STRICT_MIN_CONFIDENCE: float = 0.80           # raise minimum acceptance confidence
    STRICT_DATE_MAX_DAYS: int = 60                # tighter date window for acceptance
    STRICT_DESC_MIN: float = 0.70                 # minimum description similarity
    STRICT_REF_MIN: float = 0.70                  # minimum reference similarity when refs present
    STRICT_REQUIRE_REF_MATCH_WHEN_BOTH_PRESENT: bool = True
    STRICT_GROUP_REQUIRE_MULTIUID: bool = True    # groups must truly contain >1 unique UIDs on the multi side

    # -------- Custom Matching toggles (new) --------
    ENABLE_CUSTOM_MATCHING: bool = True
    ENABLE_CUSTOM_STRUCTURED_GROUP: bool = True
    ENABLE_CUSTOM_TRANSACTION_ID: bool = True
    ENABLE_MBB02_CC_GROUPING: bool = True
    MBB02_CC_INPUT_FOLDER: str = "CreditCardTransaction"
    # Structured group hyperparameters
    STRUCT_GROUP_DESC_VALUE: str = 'AUTOPAY DR'          # value to match in bank description (case-insensitive via preprocessing)
    MIN_STRUCTURED_GROUP_SIZE: int = 2                   # minimum number of bank rows to form a group
    STRUCT_GROUP_REQUIRE_EXACT_DATE: bool = True         # if False, allow +/- DATE_TOLERANCE_DAYS
    ENABLE_STRUCTURED_GROUP_TIEBREAKER: bool = True      # choose best company row when multiple candidates

    # -------- Experimental/Visualization (from memories) --------
    ENABLE_GRAPH_VISUALIZATION: bool = False
    SAVE_UNMATCHED_JSON: bool = False

    # Visualization params
    VIS_OUTPUT_DIR: str = "graph_visuals"
    VIS_IMAGE_FORMAT: str = "png"  # png, jpg, svg
    VIS_DPI: int = 110
    VIS_LAYOUT: str = "spring"  # spring, circular, kamada_kawai

    # Experimental matcher toggles (composite and GNN removed)
    ENABLE_GRAPH_MATCHER: bool = False
    ENABLE_TEMPORAL_MATCHER: bool = False

    # Performance
    EXP_MAX_GRAPH_NODES: int = 1500
    EXP_PARALLEL: bool = False
    EXP_MEMORY_LIMIT_MB: int = 1024

    # -------- Semantic group matching (new) --------
    ENABLE_SEMANTIC_GROUPS: bool = True
    SEM_GROUP_SIM_THRESHOLD: float = 0.60  # min semantic similarity to consider for grouping
    SEM_GROUP_TOPK: int = 8                # cap candidates per seed by semantic similarity
    SEM_GROUP_MAX_SIZE: int = 5            # default max size for semantic grouping
    ENABLE_RESERVATION_PROGRESS: bool = True  # show tqdm in reservation guard
    ENABLE_RESERVATION_DEBUG: bool = True    # log reservation candidates/groups
    RESERVATION_LOG_TO_CONSOLE: bool = True  # when debugging, also print to stdout

    # -------- Observability (Audit + Metrics) --------
    AUDIT_LOG_ENABLED: bool = True
    AUDIT_LOG_PATH: str = os.path.join("logs", "audit.log")
    METRICS_ENABLED: bool = True
    METRICS_BACKEND: str = "jsonl"  # jsonl | logger | none
    METRICS_PATH: str = os.path.join("logs", "metrics.log")

    # -------- JomPAY CR Group (Phase 1 integration) --------
    ENABLE_JOMPAY_CR_GROUP: bool = True
    JOMPAY_CONSOLIDATED_JSON: str = os.path.join("json", "phase1_jompay_consolidated.json")
    # -------- Bank-specific gating --------
    # Used to enable bank-specific rules/algorithms (e.g., MBB01 Bulk EFT)
    BANK_NAME: str = ""
    # Enable/disable the Bulk EFT matcher (applies to MBB01 by default)
    ENABLE_BULK_EFT: bool = True
    # If True, allow Bulk EFT matcher to run for any bank (ignores BANK_NAME gate)
    BULK_EFT_ALLOW_ANY_BANK: bool = False

    @classmethod
    def from_env(cls, **overrides):
        cfg = cls()
        # Load environment variables
        try:
            from dotenv import load_dotenv
            load_dotenv()
        except ImportError:
            pass  # dotenv not available, use os.getenv directly
        # Load env for key if present
        cfg.OPEN_ROUTER_KEY = overrides.get("OPEN_ROUTER_KEY") or os.getenv("OPEN_ROUTER_KEY")
        # Apply overrides
        for k, v in (overrides or {}).items():
            if not hasattr(cfg, k):
                continue
            try:
                setattr(cfg, k, v)
            except Exception:
                pass
        # Basic logging setup hint (caller may still adjust handlers)
        try:
            logging.getLogger(__name__).setLevel(getattr(logging, cfg.LOG_LEVEL, logging.INFO))
        except Exception:
            pass
        # Validate configuration to catch issues early
        try:
            cfg.validate()
        except Exception as e:
            raise ConfigurationError(f"Invalid UnifiedConfig: {e}")
        return cfg

    def validate(self) -> None:
        """Lightweight validation for critical parameters."""
        # Non-negative tolerances and days
        if self.AMOUNT_TOLERANCE < 0:
            raise ValueError("AMOUNT_TOLERANCE must be >= 0")
        if self.DATE_TOLERANCE_DAYS < 0:
            raise ValueError("DATE_TOLERANCE_DAYS must be >= 0")
        # Weights are within [0,1]
        for w_name in ("AMOUNT_WEIGHT", "DATE_WEIGHT", "REF_WEIGHT", "DESC_WEIGHT"):
            w = getattr(self, w_name, 0.0)
            if w < 0 or w > 1:
                raise ValueError(f"{w_name} must be within [0,1]")
        # AI weights within [0,1] and sum close to 1
        ai_weights = [self.AI_AMOUNT_WEIGHT, self.AI_DATE_WEIGHT, self.AI_REF_WEIGHT, self.AI_DESC_WEIGHT]
        if any(w < 0 or w > 1 for w in ai_weights):
            raise ValueError("AI weights must be within [0,1]")
        if not (0.99 <= sum(ai_weights) <= 1.01):
            raise ValueError("AI weights should sum to 1.0")
        # File mappings non-empty
        required_fields = [
            self.BANK_REF_FIELD, self.BANK_TXN_ID_FIELD, self.BANK_DATE_FIELD, self.BANK_DESC_FIELD,
            self.BANK_RECEIPT_FIELD, self.BANK_DISBURSEMENT_FIELD,
            self.COMPANY_REF_FIELD, self.COMPANY_DATE_FIELD, self.COMPANY_DESC_FIELD,
            self.COMPANY_RECEIPT_FIELD, self.COMPANY_DISBURSEMENT_FIELD,
        ]
        if any(not isinstance(f, str) or not f.strip() for f in required_fields):
            raise ValueError("Field mapping names must be non-empty strings")

        # Observability settings
        if self.METRICS_BACKEND not in ("jsonl", "logger", "none"):
            raise ValueError("METRICS_BACKEND must be one of: jsonl, logger, none")

# =============================
# Internal data classes and minimal engines
# =============================

logger = logging.getLogger(__name__)

# Prevent "No handler found" warnings in host environments
if not logger.handlers:
    logger.addHandler(logging.NullHandler())

# -----------------------------
# Custom exception types
# -----------------------------
class ReconciliationError(Exception):
    """Top-level reconciliation error wrapper for production usage."""


class DataValidationError(ReconciliationError):
    """Raised when inputs (files/JSON/content) fail validation."""


class ConfigurationError(ReconciliationError):
    """Raised when configuration is invalid or inconsistent."""


class ExportError(ReconciliationError):
    """Raised when exporting results fails in a non-recoverable way."""

# -----------------------------
# Audit logging (JSONL) and Metrics hooks
# -----------------------------
class AuditLogger:
    def __init__(self, enabled: bool, path: str, base_logger: logging.Logger):
        self.enabled = bool(enabled)
        self.path = path
        self.logger = base_logger
        if self.enabled:
            try:
                os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            except Exception:
                # Fallback: disable if path cannot be created
                self.enabled = False

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        try:
            payload = {
                "ts": datetime.utcnow().isoformat() + "Z",
                "event": event_type,
                **(data or {}),
            }
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except Exception as e:
            # Don't crash the pipeline for audit failures
            try:
                self.logger.debug(f"Audit write failed: {e}")
            except Exception:
                pass


class MetricsHook:
    def __init__(self, enabled: bool, backend: str, path: str, base_logger: logging.Logger):
        self.enabled = bool(enabled)
        self.backend = backend or "none"
        self.path = path
        self.logger = base_logger
        if self.enabled and self.backend == "jsonl":
            try:
                os.makedirs(os.path.dirname(self.path) or '.', exist_ok=True)
            except Exception:
                self.backend = "logger"

    def _emit(self, record: Dict[str, Any]) -> None:
        if not self.enabled:
            return
        record = {**record, "ts": datetime.utcnow().isoformat() + "Z"}
        try:
            if self.backend == "jsonl":
                with open(self.path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
            elif self.backend == "logger":
                self.logger.debug(f"METRIC {record}")
            else:
                # none -> drop
                return
        except Exception:
            # do not crash on metrics failures
            pass

    def incr(self, name: str, value: int = 1, tags: Optional[Dict[str, Any]] = None) -> None:
        self._emit({"type": "counter", "name": name, "value": int(value), "tags": tags or {}})

    def observe(self, name: str, value: float, tags: Optional[Dict[str, Any]] = None) -> None:
        self._emit({"type": "gauge", "name": name, "value": float(value), "tags": tags or {}})

    def timing(self, name: str, tags: Optional[Dict[str, Any]] = None):
        class _Ctx:
            def __init__(self, outer: 'MetricsHook'):
                self.o = outer
                self.start = None
                self.name = name
                self.tags = tags or {}
            def __enter__(self):
                self.start = time.perf_counter()
                return self
            def __exit__(self, exc_type, exc, tb):
                try:
                    dur_ms = (time.perf_counter() - self.start) * 1000.0
                    self.o._emit({"type": "timing", "name": self.name, "value": dur_ms, "tags": self.tags})
                except Exception:
                    pass
        return _Ctx(self)


# -----------------------------
# Tee stdout/stderr to file (per-run)
# -----------------------------
class _TeeTextIO(io.TextIOBase):
    """A minimal TextIO that writes to two underlying text streams.
    Used to duplicate stdout/stderr both to console and a log file.
    """
    def __init__(self, a: io.TextIOBase, b: io.TextIOBase):
        self.a = a
        self.b = b

    def writable(self) -> bool:
        try:
            return (self.a.writable() if hasattr(self.a, 'writable') else True) or (self.b.writable() if hasattr(self.b, 'writable') else True)
        except Exception:
            return True

    def write(self, s: str):
        # Best-effort write to both streams
        try:
            self.a.write(s)
        except Exception:
            pass
        try:
            self.b.write(s)
        except Exception:
            pass
        try:
            self.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            if hasattr(self.a, 'flush'):
                self.a.flush()
        except Exception:
            pass
        try:
            if hasattr(self.b, 'flush'):
                self.b.flush()
        except Exception:
            pass


class TeeStdStreams:
    """Context manager that tees sys.stdout and sys.stderr to a file.

    Ensures that anything printed (including tqdm progress bars targeting stdout)
    and any traceback emitted to stderr are also persisted to the provided file.
    """
    def __init__(self, log_path: str, encoding: str = 'utf-8'):
        self.log_path = log_path
        self.encoding = encoding
        self._orig_stdout = None
        self._orig_stderr = None
        self._file = None

    def __enter__(self):
        # Prepare directory and file
        os.makedirs(os.path.dirname(self.log_path) or '.', exist_ok=True)
        self._file = open(self.log_path, 'a', encoding=self.encoding, buffering=1)

        # Keep originals
        self._orig_stdout = sys.stdout
        self._orig_stderr = sys.stderr

        # Wrap originals to ensure text mode
        file_writer = self._file
        sys.stdout = _TeeTextIO(self._orig_stdout, file_writer)
        sys.stderr = _TeeTextIO(self._orig_stderr, file_writer)
        return self

    def __exit__(self, exc_type, exc, tb):
        # Restore streams
        try:
            if self._orig_stdout is not None:
                sys.stdout = self._orig_stdout
            if self._orig_stderr is not None:
                sys.stderr = self._orig_stderr
        except Exception:
            pass
        # Close file last
        try:
            if self._file:
                self._file.flush()
                self._file.close()
        except Exception:
            pass

@dataclass
class MatchResult:
    """Result of a match between bank and company transactions."""
    bank_tx_id: Union[str, int]
    company_tx_id: Union[str, int, List[Union[str, int]]]
    match_score: float
    match_type: str
    transaction_type: str
    amount_diff: float
    date_diff: int
    explanation: str
    bank_data: dict
    company_data: Union[dict, List[dict]]
    ai_confidence: Optional[float] = None
    ai_explanation: Optional[str] = None
    verification_status: Optional[str] = None

class EnhancedReconciliationConfig:
    """Configuration for EnhancedReconciler (defaults; will be overridden from UnifiedConfig)."""
    # Logging
    LOG_LEVEL = 'DEBUG'
    LOG_TO_FILE = True
    # Date format
    DATE_FORMAT = "%Y-%m-%d"
    # Thresholds
    AMOUNT_TOLERANCE = 0.0
    DATE_TOLERANCE_DAYS = 100
    MIN_FUZZY_SCORE = 70
    MIN_MATCH_SCORE = 0.7
    # Grouping
    MAX_GROUP_SIZE = 3
    MAX_GROUP_DATE_RANGE = 100
    MIN_GROUP_SCORE = 50
    MAX_GROUP_AMOUNT_DIFF_PCT = 0.0
    # MAX_TRANSACTIONS_TO_CONSIDER = 30
    # MAX_COMBINATIONS_TO_TRY = 2000
    MAX_TRANSACTIONS_TO_CONSIDER = 1000
    MAX_COMBINATIONS_TO_TRY = 3000
    # Weights
    AMOUNT_WEIGHT = 0.5
    DATE_WEIGHT = 0.2
    REF_WEIGHT = 0.2
    DESC_WEIGHT = 0.1
    # Output
    OUTPUT_DECIMALS = 2
    # Field mappings - Bank
    BANK_REF_FIELD = "Ext. Ref. Nbr."
    BANK_TXN_ID_FIELD = "Ext. Tran. ID"
    BANK_DATE_FIELD = "Tran. Date"
    BANK_DESC_FIELD = "Tran. Desc"
    BANK_RECEIPT_FIELD = "Receipt"
    BANK_DISBURSEMENT_FIELD = "Disbursement"
    # Field mappings - Company
    COMPANY_REF_FIELD = "Document Ref."
    COMPANY_DATE_FIELD = "Doc. Date"
    COMPANY_DESC_FIELD = "Description"
    COMPANY_RECEIPT_FIELD = "Receipt"
    COMPANY_DISBURSEMENT_FIELD = "Disbursement"

class EnhancedReconciler:
    """Handles reconciliation between bank transactions and company statements with optimized matching."""

    def __init__(self, config: Optional[EnhancedReconciliationConfig] = None):
        self.config = config if config else EnhancedReconciliationConfig()
        self.bank_df: Optional[pd.DataFrame] = None
        self.company_df: Optional[pd.DataFrame] = None
        self.matched_company_ids: Set[Any] = set()
        self.matched_bank_ids: Set[Any] = set()
        self._error_records: List[Dict[str, Any]] = []
        self._external_error_records: Optional[List[Dict[str, Any]]] = None

    def load_data_from_dicts(self, bank_data: List[Dict[str, Any]], company_data: List[Dict[str, Any]]):
        # Convert to DataFrames and ensure UID is set as index and kept as column
        self.bank_df = self._preserve_uid(pd.DataFrame(bank_data))
        self.company_df = self._preserve_uid(pd.DataFrame(company_data))
        # Track UID universes
        self.bank_uids = set(self.bank_df.index)
        self.company_uids = set(self.company_df.index)
        # Preprocess
        self._preprocess_data()
        logger.info(f"Loaded {len(self.bank_df)} bank transactions and {len(self.company_df)} company transactions")
        # Reset error buffer for each load
        self._error_records = []
        self._external_error_records = None

    def find_mbb02_creditcard_group_matches(self) -> List[MatchResult]:
        """
        Custom: Match MBB02 credit card deposits against company references extracted
        from the credit card transaction files. Requires that every reference identified
        in the supporting document exists in the company statements before producing a match.
        """
        results: List[MatchResult] = []
        if not getattr(self.config, 'ENABLE_CUSTOM_MATCHING', True):
            return results
        if not getattr(self.config, 'ENABLE_MBB02_CC_GROUPING', True):
            return results
        if str(getattr(self.config, 'BANK_NAME', '')).strip().upper() != 'MBB02':
            return results
        if mbb02_cc is None:
            logger.debug("MBB02 credit card matcher skipped: support module not available")
            return results
        if self.bank_df is None or self.company_df is None:
            return results

        input_folder = getattr(self.config, 'MBB02_CC_INPUT_FOLDER', 'CreditCardTransaction') or ''
        folder_path = Path(input_folder)
        if not folder_path.exists():
            logger.debug("MBB02 credit card matcher skipped: folder not found (%s)", folder_path)
            return results

        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        if unmatched_bank.empty:
            return results

        comp_ref_col = self.config.COMPANY_REF_FIELD
        comp_receipt_col = self.config.COMPANY_RECEIPT_FIELD
        comp_disb_col = self.config.COMPANY_DISBURSEMENT_FIELD
        bank_desc_col = self.config.BANK_DESC_FIELD
        bank_receipt_col = self.config.BANK_RECEIPT_FIELD
        bank_disb_col = self.config.BANK_DISBURSEMENT_FIELD
        bank_date_col = self.config.BANK_DATE_FIELD
        amt_tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)

        seen_keys: Set[Tuple[str, str, str]] = set()

        def _to_float(val: Any) -> float:
            try:
                if val is None:
                    return 0.0
                if isinstance(val, (int, float)):
                    return float(val)
                s = str(val).strip()
                if not s:
                    return 0.0
                return float(s.replace(',', ''))
            except Exception:
                return 0.0

        for b_idx, bank_row in unmatched_bank.iterrows():
            desc = str(bank_row.get(bank_desc_col, '') or '').strip()
            if not desc:
                continue
            try:
                parsed = mbb02_cc.parse_mbb02_tran_desc(desc)
            except Exception:
                parsed = None
            if not parsed:
                continue
            tx_type, number, bank_date_iso = parsed
            key = (tx_type, number, bank_date_iso)
            if key in seen_keys:
                continue
            seen_keys.add(key)

            try:
                match_payload = mbb02_cc.process_for_desc_in_memory(
                    bank_name='MBB02',
                    tran_desc=desc,
                    input_folder=str(folder_path),
                )
            except Exception:
                continue
            matched_files = match_payload.get('matched_files', [])
            if not matched_files:
                continue

            all_refs: List[str] = []
            cc_net_total = 0.0
            cc_net_available = False
            for file_entry in matched_files:
                refs = [str(r).strip() for r in file_entry.get('reference_numbers', []) if str(r).strip()]
                if refs:
                    all_refs.extend(refs)
                net_val = file_entry.get('net_amount')
                if net_val is not None and str(net_val).strip() != '':
                    cc_net_available = True
                cc_net_total += _to_float(net_val)
            if not all_refs:
                continue

            ref_counter = Counter(all_refs)

            unmatched_company = self.company_df[~self.company_df.index.isin(self.matched_company_ids)] if hasattr(self, 'matched_company_ids') else self.company_df
            if unmatched_company.empty:
                continue
            company_refs = unmatched_company[comp_ref_col].fillna('').astype(str).str.strip()
            available_counter = Counter(company_refs)
            missing = sorted({ref for ref, cnt in ref_counter.items() if available_counter.get(ref, 0) < cnt})
            if missing:
                self._record_mbb02_error(bank_row, missing)
                print(f"find_mbb02_creditcard_group_matches failed: {missing}")
                continue

            candidate_mask = company_refs.isin(ref_counter.keys())
            candidates = unmatched_company[candidate_mask]
            selected_indices: List[Any] = []
            for ref in all_refs:
                norm_ref = ref.strip()
                sub_df = candidates[candidates[comp_ref_col].fillna('').astype(str).str.strip() == norm_ref]
                sub_df = sub_df[~sub_df.index.isin(selected_indices)]
                if sub_df.empty:
                    err_refs = sorted(set(missing or []) | {norm_ref})
                    self._record_mbb02_error(bank_row, err_refs)
                    print(f"find_mbb02_creditcard_group_matches failed: {err_refs}")
                    selected_indices = []
                    break
                selected_indices.append(sub_df.index[0])
            if not selected_indices:
                continue

            company_selection = self.company_df.loc[selected_indices]

            receipt_sum = pd.to_numeric(company_selection[comp_receipt_col], errors='coerce').fillna(0).sum()
            disb_sum = pd.to_numeric(company_selection[comp_disb_col], errors='coerce').fillna(0).sum()
            company_net = float(receipt_sum - disb_sum)

            bank_receipt = _to_float(bank_row.get(bank_receipt_col))
            bank_disb = _to_float(bank_row.get(bank_disb_col))
            bank_net = bank_receipt - bank_disb

            if abs(bank_net - company_net) > amt_tol:
                print("CreditcardTransaction Group Insufficient")
                continue
            if cc_net_available and abs(bank_net - cc_net_total) > max(amt_tol, 0.01):
                print("CreditcardTransaction Group Insufficient")
                continue

            bank_date = bank_row.get(bank_date_col)
            date_diff = 0
            if isinstance(bank_date, pd.Timestamp):
                diffs = []
                for comp_date in company_selection[self.config.COMPANY_DATE_FIELD]:
                    if isinstance(comp_date, pd.Timestamp):
                        diffs.append(abs((bank_date - comp_date).days))
                if diffs:
                    date_diff = max(diffs)

            bank_dict = bank_row.to_dict()
            company_dicts = [self.company_df.loc[idx].to_dict() for idx in selected_indices]
            amount_diff = abs(bank_net - company_net)
            unique_refs_display = list(dict.fromkeys(all_refs))

            explanation = (
                f"MBB02 credit card group match: {len(selected_indices)} company refs "
                f"({', '.join(unique_refs_display)}). "
                f"Bank net RM {bank_net:,.2f} vs company net RM {company_net:,.2f}."
            )

            results.append(MatchResult(
                bank_tx_id=bank_dict.get('UID', b_idx),
                company_tx_id=[self.company_df.loc[idx].get('UID', idx) for idx in selected_indices],
                match_score=100.0,
                match_type='mbb02_creditcard_group',
                transaction_type=str(bank_row.get('txn_type', tx_type or 'credit_card')),
                amount_diff=amount_diff,
                date_diff=date_diff,
                explanation=explanation,
                bank_data=bank_dict,
                company_data=company_dicts,
            ))

            self.matched_bank_ids.add(b_idx)
            for idx in selected_indices:
                self.matched_company_ids.add(idx)

        return results

    def _record_mbb02_error(self, bank_row: pd.Series, missing_refs: List[str]) -> None:
        """Store missing reference information for MBB02 credit card groups to emit in the Excel error sheet."""
        try:
            headers = self._get_column_headers()
        except Exception:
            headers = [
                'Bank Statement Date', 'Bank Transaction ID', 'Bank Reference Number',
                'Bank Description', 'Bank Receipt', 'Bank Disbursement',
                'CSGP Transaction Date', 'CSGP Reference', 'CSGP Module', 'CSGP Description',
                'CSGP Receipt', 'CSGP Disbursement',
                'Amount Difference', 'Date Difference', 'Reason',
                'Confidence', 'Match Type', 'Bank_UID', 'CSGP_UID'
            ]
        row = {col: '' for col in headers}
        sorted_missing = sorted(set(missing_refs))
        remark_text = f"Missing Document Ref.: {', '.join(sorted_missing)}" if sorted_missing else "Missing Document Ref."
        row['Remark'] = remark_text

        def safe_str(value: Any) -> str:
            try:
                if value is None or (isinstance(value, float) and pd.isna(value)):
                    return ''
                if isinstance(value, (pd.Timestamp, datetime)):
                    try:
                        return value.strftime(getattr(self.config, 'DATE_FORMAT', '%Y-%m-%d'))
                    except Exception:
                        return str(value)
                return str(value)
            except Exception:
                return ''

        def safe_amount(value: Any) -> float:
            try:
                num = pd.to_numeric(value, errors='coerce')
                if pd.isna(num):
                    return 0.0
                return float(num)
            except Exception:
                return 0.0

        row['Bank Statement Date'] = safe_str(bank_row.get('Tran. Date'))
        row['Bank Transaction ID'] = safe_str(bank_row.get('Ext. Tran. ID'))
        row['Bank Reference Number'] = safe_str(bank_row.get('Ext. Ref. Nbr.'))
        row['Bank Description'] = safe_str(bank_row.get('Tran. Desc'))
        receipt = safe_amount(bank_row.get('Receipt'))
        disbursement = safe_amount(bank_row.get('Disbursement'))
        row['Bank Receipt'] = safe_str(receipt) if receipt > 0 else ''
        row['Bank Disbursement'] = safe_str(disbursement) if disbursement > 0 else ''
        row['Match Type'] = 'mbb02_creditcard_group_error'
        row['Reason'] = 'Missing Document Ref.'
        row['Bank_UID'] = safe_str(bank_row.get('UID'))

        row.setdefault('CSGP_UID', '')
        self._error_records.append(row)
        sink = getattr(self, '_external_error_records', None)
        if sink is not None and sink is not self._error_records:
            sink.append(row.copy())

    def find_custom_structured_group_matches(self) -> List[MatchResult]:
        """Custom: Structured Group Matching

        If bank transactions have Tran. Desc == 'AUTOPAY DR' and share the same
        Ext. Ref. Nbr. and Tran. Date, classify them as a group (n:1).
        Then find a company transaction with the exact same Doc. Date and equal
        sum(net_amount) to the group's total (respecting AMOUNT_TOLERANCE).
        """
        results: List[MatchResult] = []
        if not getattr(self.config, 'ENABLE_CUSTOM_MATCHING', True):
            return results
        if not getattr(self.config, 'ENABLE_CUSTOM_STRUCTURED_GROUP', True):
            return results
        if self.bank_df is None or self.company_df is None:
            return results

        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        if unmatched_bank.empty:
            return results

        desc_col = self.config.BANK_DESC_FIELD
        ref_col = self.config.BANK_REF_FIELD
        date_col_b = self.config.BANK_DATE_FIELD
        date_col_c = self.config.COMPANY_DATE_FIELD
        amt_tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)

        # Case-insensitive: preprocessing uppercased text columns, so compare to upper value
        target_desc = str(getattr(self.config, 'STRUCT_GROUP_DESC_VALUE', 'AUTOPAY DR') or 'AUTOPAY DR').upper()
        autopay = unmatched_bank[unmatched_bank[desc_col].astype(str) == target_desc]
        if autopay.empty:
            return results

        # Group by ref and date (exact); if configured to allow tolerance, we'll relax match for company side only
        grp = autopay.groupby([ref_col, date_col_b])
        for (ref_val, b_date), g in grp:
            try:
                min_size = max(2, int(getattr(self.config, 'MIN_STRUCTURED_GROUP_SIZE', 2) or 2))
                if g.shape[0] < min_size:
                    continue
                group_sum = float(pd.to_numeric(g['net_amount'], errors='coerce').fillna(0).sum())
                types = set(g['txn_type'].astype(str).tolist())
                if len(types) != 1:
                    continue
                b_type = list(types)[0]

                unmatched_company = self.company_df[~self.company_df.index.isin(self.matched_company_ids)] if hasattr(self, 'matched_company_ids') else self.company_df
                # Date constraint for company side
                if bool(getattr(self.config, 'STRUCT_GROUP_REQUIRE_EXACT_DATE', True)):
                    same_date = unmatched_company[unmatched_company[date_col_c] == b_date]
                else:
                    tol_days = int(getattr(self.config, 'DATE_TOLERANCE_DAYS', 0) or 0)
                    lower = b_date - pd.Timedelta(days=tol_days)
                    upper = b_date + pd.Timedelta(days=tol_days)
                    same_date = unmatched_company[unmatched_company[date_col_c].between(lower, upper)]
                if same_date.empty:
                    continue
                same_type = same_date[same_date['txn_type'] == b_type]
                if same_type.empty:
                    continue
                amt_diff_series = (same_type['net_amount'] - group_sum).abs()
                exact_match = same_type[amt_diff_series <= amt_tol]
                if exact_match.empty:
                    continue
                # Resolve multiple candidates
                if len(exact_match) == 1 or not bool(getattr(self.config, 'ENABLE_STRUCTURED_GROUP_TIEBREAKER', True)):
                    c_idx, comp_tx = next(iter(exact_match.iterrows()))
                else:
                    # Tie-breaker: prefer company row whose description or reference best matches the bank ref
                    # This is optional and can be disabled via config
                    best = None
                    best_score = -1
                    for ci, row in exact_match.iterrows():
                        c_desc = str(row.get(self.config.COMPANY_DESC_FIELD, '') or '')
                        c_ref = str(row.get(self.config.COMPANY_REF_FIELD, '') or '')
                        s1 = fuzz.token_set_ratio(str(ref_val or ''), c_desc)
                        s2 = fuzz.token_set_ratio(str(ref_val or ''), c_ref)
                        score = max(s1, s2)
                        if score > best_score:
                            best_score = score
                            best = (ci, row)
                    if best is None:
                        c_idx, comp_tx = next(iter(exact_match.iterrows()))
                    else:
                        c_idx, comp_tx = best

                bank_dicts = [row.to_dict() for _, row in g.iterrows()]
                bank_ids = [d.get('UID', d.get(self.config.BANK_REF_FIELD)) for d in bank_dicts]
                comp_dict = comp_tx.to_dict()
                if 'UID' not in comp_dict and self.config.COMPANY_REF_FIELD in comp_dict:
                    comp_dict['UID'] = comp_dict[self.config.COMPANY_REF_FIELD]

                results.append(MatchResult(
                    bank_tx_id=bank_ids,
                    company_tx_id=comp_dict['UID'],
                    match_score=100.0,
                    match_type='custom_structured_group',
                    transaction_type=b_type,
                    amount_diff=0.0,
                    date_diff=0,
                    explanation=(
                        f"Custom Structured Group: AUTOPAY DR grouped by {ref_col}={ref_val} and date {b_date.strftime('%Y-%m-%d')}. "
                        f"{len(g)} bank items, sum=RM {group_sum:.2f}, matched company UID={comp_dict['UID']} on exact date and amount."
                    ),
                    bank_data=bank_dicts,
                    company_data=comp_dict,
                ))

                if hasattr(self, 'matched_company_ids'):
                    self.matched_company_ids.add(c_idx)
                if hasattr(self, 'matched_bank_ids'):
                    for bi in g.index:
                        self.matched_bank_ids.add(bi)
            except Exception:
                continue

        logger.info(f"Custom Structured Group matched {len(results)} groups")
        return results

    def find_bulk_eft_matches(self) -> List[MatchResult]:
        """Bulk EFT N:1 matching using L+yymm+EFT reference pattern (MBB01 default).

        Scenario 1: Exact bulk EFT
        - Bank: Many rows share same reference like 'L2508055380812' (L + yymm + EFT number)
        - GL: One row contains only the EFT number (e.g., '055380812') in ref/description
        - Amount difference: 0 (sum(bank group) == company amount)

        Scenario 2: Bulk EFT with rejected transactions
        - Same as above, but amount difference != 0. Still produce a grouped match and
          surface the difference so analysts can review.

        This matcher is gated to run only when config.BANK_NAME == 'MBB01' (unless overridden).
        """
        results: List[MatchResult] = []
        try:
            # Gate by enable flag and bank name (or explicit override)
            # Respect explicit enable flag; bank gating is handled by the orchestrator
            if not bool(getattr(self.config, 'ENABLE_BULK_EFT', True)):
                return results
            if self.bank_df is None or self.company_df is None:
                return results

            ref_b = self.config.BANK_REF_FIELD
            date_b = self.config.BANK_DATE_FIELD
            ref_c = self.config.COMPANY_REF_FIELD
            desc_c = self.config.COMPANY_DESC_FIELD
            decimals = int(getattr(self.config, 'OUTPUT_DECIMALS', 2) or 2)
            amt_tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)

            # Pattern: L + yymm + EFT number (EFT digits length can vary; typically 8-10)
            # Capture EFT as group 2
            patt = re.compile(r"^L(\d{4})(\d{6,12})$", re.IGNORECASE)

            # Work on unmatched items only
            unmatched_bank = self.bank_df[~self.bank_df.index.isin(getattr(self, 'matched_bank_ids', set()))]
            unmatched_company = self.company_df[~self.company_df.index.isin(getattr(self, 'matched_company_ids', set()))]
            if unmatched_bank.empty or unmatched_company.empty:
                return results

            # Extract EFT number from bank references and group by full ref value
            temp = unmatched_bank.copy()
            temp['__bulk_ref'] = temp.get(ref_b, '').astype(str)
            temp['__bulk_match'] = temp['__bulk_ref'].str.extract(r"^(L\d{4}\d{6,12})$", expand=False)
            temp['__bulk_eft'] = temp['__bulk_ref'].str.extract(r"^L\d{4}(\d{6,12})$", expand=False)
            # Keep only rows that follow the pattern
            temp = temp[~temp['__bulk_match'].isna()]
            if temp.empty:
                return results

            # Group by the exact L+yymm+EFT reference; within each group, sum net_amount
            by_ref = temp.groupby(['__bulk_match'])
            for lref, g in by_ref:
                try:
                    eft_num = str(g['__bulk_eft'].iloc[0] or '').strip()
                    if not eft_num:
                        continue
                    # Sum only disbursement amounts for matching, but include all rows in the group
                    disb_rows = g[g['txn_type'].astype(str) == 'disbursement']
                    rec_rows = g[g['txn_type'].astype(str) == 'receipt']
                    group_sum = float(pd.to_numeric(disb_rows['net_amount'], errors='coerce').fillna(0).sum())
                    # Always match against company disbursement rows for this scenario
                    b_type = 'disbursement'

                    # Candidate company rows: contain EFT number in ref or description (case-insensitive)
                    contains_eft = unmatched_company[
                        unmatched_company[ref_c].astype(str).str.contains(eft_num, case=False, na=False) |
                        unmatched_company[desc_c].astype(str).str.contains(eft_num, case=False, na=False)
                    ]
                    if contains_eft.empty:
                        continue

                    # Further narrow by txn type (company disbursement only)
                    contains_eft = contains_eft[contains_eft['txn_type'] == 'disbursement']
                    if contains_eft.empty:
                        continue

                    # Choose the company row with the smallest amount difference; prefer exact match
                    diffs = (contains_eft['net_amount'] - group_sum).abs()
                    best_idx = diffs.sort_values().index[0]
                    comp_tx = contains_eft.loc[best_idx]
                    company_net = float(comp_tx['net_amount'])
                    amount_diff = round(abs(group_sum - company_net), decimals)

                    # Prepare payloads
                    bank_dicts = [row.to_dict() for _, row in g.iterrows()]
                    bank_ids = [d.get('UID', d.get(ref_b)) for d in bank_dicts]
                    company_dict = comp_tx.to_dict()
                    if 'UID' not in company_dict and ref_c in company_dict:
                        company_dict['UID'] = company_dict[ref_c]

                    scenario = 'custom_bulk_eft' if amount_diff <= max(amt_tol, 0.0) else 'custom_bulk_eft_with_rejects'
                    explain = (
                        f"Bulk EFT via EFT={eft_num}. "
                        f"Group {len(g)} bank items with ref {lref} (disb={len(disb_rows)}, receipt={len(rec_rows)}); "
                        f"disbursement-sum=RM {group_sum:.2f} (receipts excluded from sum). "
                        f"Matched 1 company UID={company_dict.get('UID')} amount=RM {company_net:.2f}. "
                        f"Diff=RM {amount_diff:.2f}."
                    )

                    results.append(MatchResult(
                        bank_tx_id=bank_ids,
                        company_tx_id=company_dict['UID'],
                        match_score=100.0 if amount_diff <= max(amt_tol, 0.0) else 90.0,
                        match_type=scenario,
                        transaction_type='disbursement',
                        amount_diff=amount_diff,
                        date_diff=0,
                        explanation=explain,
                        bank_data=bank_dicts,
                        company_data=company_dict,
                    ))

                    # Reserve matched IDs to prevent reuse
                    if hasattr(self, 'matched_company_ids'):
                        self.matched_company_ids.add(comp_tx.name)
                    if hasattr(self, 'matched_bank_ids'):
                        for bi in g.index:
                            self.matched_bank_ids.add(bi)
                except Exception:
                    continue
            return results
        except Exception:
            return results

    # -----------------------------
    # JomPAY CR Group Matching (Phase 1 JSON feed)
    # -----------------------------
    def find_jompay_cr_group_matches_from_json(self, json_path: Optional[str] = None) -> List[MatchResult]:
        """
        Match company JomPAY refs to a single bank AUTOPAY CR:
        - Company: Document Ref. must contain all refs in the JSON group for the exact Doc. Date,
          and the sum of Receipt equals JSON total_amount (exact at OUTPUT_DECIMALS).
        - Bank: a single row with Tran. Desc == 'AUTOPAY CR' on the previous day whose net_amount
          equals JSON total_net_amount (exact at OUTPUT_DECIMALS).
        """
        results: List[MatchResult] = []
        try:
            if not getattr(self.config, 'ENABLE_CUSTOM_MATCHING', True):
                return results
            if not getattr(self.config, 'ENABLE_JOMPAY_CR_GROUP', True):
                return results
            if self.bank_df is None or self.company_df is None:
                return results

            jpath = Path(json_path or getattr(self.config, 'JOMPAY_CONSOLIDATED_JSON', 'json/phase1_jompay_consolidated.json'))
            if not jpath.exists():
                print("Jompay CR Group Skip")
                return results

            try:
                payload = json.loads(jpath.read_text(encoding='utf-8'))
            except Exception:
                print("Jompay CR Group Skip")
                return results

            groups = payload.get('groups', []) or []
            if not groups:
                return results

            ref_col = self.config.COMPANY_REF_FIELD  # 'Document Ref.'
            if ref_col not in self.company_df.columns:
                print("Jompay CR Group Skip")
                return results

            date_c = self.config.COMPANY_DATE_FIELD
            date_b = self.config.BANK_DATE_FIELD
            desc_b = self.config.BANK_DESC_FIELD
            decimals = int(getattr(self.config, 'OUTPUT_DECIMALS', 2) or 2)

            unmatched_company = self.company_df[~self.company_df.index.isin(getattr(self, 'matched_company_ids', set()))]
            unmatched_bank = self.bank_df[~self.bank_df.index.isin(getattr(self, 'matched_bank_ids', set()))]

            for g in groups:
                try:
                    g_date_str = str(g.get('date') or '').strip()
                    if not g_date_str:
                        print("Jompay CR Group Skip")
                        continue
                    g_date = pd.to_datetime(g_date_str, format=getattr(self.config, 'DATE_FORMAT', '%Y-%m-%d'), errors='coerce')
                    if pd.isna(g_date):
                        print("Jompay CR Group Skip")
                        continue
                    refs = [str(x).strip().upper() for x in (g.get('jompay_ref_nos') or []) if str(x).strip()]
                    if not refs:
                        print("Jompay CR Group Skip")
                        continue
                    set_refs = set(refs)

                    # Company side selection
                    comp_matches = unmatched_company[unmatched_company[ref_col].astype(str).str.strip().str.upper().isin(set_refs)]
                    found_refs = set(comp_matches[ref_col].astype(str).str.strip().str.upper().tolist())
                    if set_refs - found_refs:
                        print("Jompay CR Group Skip")
                        continue
                    if comp_matches.empty or date_c not in comp_matches.columns:
                        print("Jompay CR Group Skip")
                        continue
                    # exact same date for all rows
                    all_dates = comp_matches[date_c].dropna().dt.normalize().unique()
                    if len(all_dates) != 1 or pd.Timestamp(all_dates[0]) != pd.Timestamp(g_date.normalize()):
                        print("Jompay CR Group Skip")
                        continue

                    # Sum Receipt only, exact equality to total_amount
                    if self.config.COMPANY_RECEIPT_FIELD not in comp_matches.columns:
                        print("Jompay CR Group Skip")
                        continue
                    sum_receipt = pd.to_numeric(comp_matches[self.config.COMPANY_RECEIPT_FIELD], errors='coerce').fillna(0).sum()
                    json_total_amount = float(g.get('total_amount', 0.0) or 0.0)
                    if round(float(sum_receipt), decimals) != round(json_total_amount, decimals):
                        print("Jompay CR Group Skip")
                        continue

                    # Bank side: AUTOPAY CR next day, exact amount equals total_net_amount
                    expected_bank_date = (pd.Timestamp(g_date) + pd.Timedelta(days=1)).normalize()
                    bank_candidates = unmatched_bank[
                        (unmatched_bank[desc_b].astype(str) == 'AUTOPAY CR')
                        & (unmatched_bank[date_b].dt.normalize() == expected_bank_date)
                    ]
                    if bank_candidates.empty:
                        print("Jompay CR Group Skip")
                        continue
                    json_total_net = float(g.get('total_net_amount', 0.0) or 0.0)
                    exact_bank = bank_candidates[bank_candidates['net_amount'].round(decimals) == round(json_total_net, decimals)]
                    if exact_bank.empty:
                        print("Jompay CR Group Skip")
                        continue

                    b_idx, b_row = next(iter(exact_bank.iterrows()))
                    comp_ids = comp_matches.index.tolist()
                    explanation = (
                        f"JomPAY CR Group: {len(comp_ids)} refs on {g_date.strftime('%Y-%m-%d')} -> "
                        f"AUTOPAY CR on next day {expected_bank_date.strftime('%Y-%m-%d')} amount=RM {json_total_net:.2f}"
                    )
                    results.append(MatchResult(
                        bank_tx_id=str(b_idx),
                        company_tx_id=[str(x) for x in comp_ids],
                        match_score=100.0,
                        match_type='jompay_cr_group',
                        transaction_type=str(b_row.get('txn_type', 'receipt')),
                        amount_diff=0.0,
                        date_diff=1,
                        explanation=explanation,
                        bank_data=b_row.to_dict(),
                        company_data=[self.company_df.loc[cid].to_dict() for cid in comp_ids],
                    ))

                    # Reserve matched IDs
                    if hasattr(self, 'matched_bank_ids'):
                        self.matched_bank_ids.add(b_idx)
                    if hasattr(self, 'matched_company_ids'):
                        for cid in comp_ids:
                            self.matched_company_ids.add(cid)
                except Exception:
                    print("Jompay CR Group Skip")
                    continue

            if results:
                logging.getLogger(__name__).info(f"JomPAY CR Group matched {len(results)} groups")
            return results
        except Exception:
            print("Jompay CR Group Skip")
            return results

    def _preserve_uid(self, df: pd.DataFrame, uid_col: str = 'UID') -> pd.DataFrame:
        if uid_col not in df.columns:
            raise KeyError(f"{uid_col} column not found")
        df[uid_col] = df[uid_col].astype(str)
        return df.set_index(uid_col, drop=False)

    def _preprocess_data(self) -> None:
        # Dates
        for field, frame in [
            (self.config.BANK_DATE_FIELD, self.bank_df),
            (self.config.COMPANY_DATE_FIELD, self.company_df),
        ]:
            if field in frame.columns:
                frame[field] = pd.to_datetime(frame[field], format=self.config.DATE_FORMAT, errors='coerce')
        # Text
        for frame, fields in [
            (self.bank_df, [self.config.BANK_REF_FIELD, self.config.BANK_DESC_FIELD]),
            (self.company_df, [self.config.COMPANY_REF_FIELD, self.config.COMPANY_DESC_FIELD]),
        ]:
            for col in fields:
                if col in frame.columns:
                    frame[col] = frame[col].astype(str).str.strip().str.upper()
        # Amounts and txn features
        for frame, rcol, dcol in [
            (self.bank_df, self.config.BANK_RECEIPT_FIELD, self.config.BANK_DISBURSEMENT_FIELD),
            (self.company_df, self.config.COMPANY_RECEIPT_FIELD, self.config.COMPANY_DISBURSEMENT_FIELD),
        ]:
            if rcol in frame.columns and dcol in frame.columns:
                frame[f'{rcol}_original'] = frame[rcol].copy()
                frame[f'{dcol}_original'] = frame[dcol].copy()
                frame[rcol] = pd.to_numeric(frame[rcol], errors='coerce').fillna(0).abs()
                frame[dcol] = pd.to_numeric(frame[dcol], errors='coerce').fillna(0).abs()
                frame['net_amount'] = (frame[rcol] - frame[dcol]).abs()
                frame['txn_type'] = np.where(
                    (pd.to_numeric(frame[rcol], errors='coerce').fillna(0) - pd.to_numeric(frame[dcol], errors='coerce').fillna(0)) >= 0,
                    'receipt',
                    'disbursement'
                )
                zero_mask = (frame['net_amount'].abs() < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) & ((frame[rcol] > 0) | (frame[dcol] > 0))
                frame.loc[zero_mask, 'txn_type'] = np.where(frame.loc[zero_mask, rcol] >= frame.loc[zero_mask, dcol], 'receipt', 'disbursement')

    def _get_transaction_type(self, row: Any, is_bank: bool = True) -> str:
        def _safe_num(x: Any) -> float:
            try:
                if isinstance(x, (pd.Series, np.ndarray, list, tuple)):
                    v = pd.to_numeric(x, errors='coerce')
                    try:
                        return float(np.nansum(v))
                    except Exception:
                        return float(pd.Series(v).sum(skipna=True))
                v = pd.to_numeric(x, errors='coerce')
                return 0.0 if pd.isna(v) else float(v)
            except Exception:
                try:
                    return float(x)
                except Exception:
                    return 0.0

        if is_bank:
            rfield = self.config.BANK_RECEIPT_FIELD
            dfield = self.config.BANK_DISBURSEMENT_FIELD
        else:
            rfield = self.config.COMPANY_RECEIPT_FIELD
            dfield = self.config.COMPANY_DISBURSEMENT_FIELD

        try:
            if isinstance(row, pd.DataFrame):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            elif isinstance(row, pd.Series):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            elif isinstance(row, dict):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            else:
                receipt = 0.0
                disb = 0.0
        except Exception:
            receipt = 0.0
            disb = 0.0

        if receipt >= disb and (receipt > 0 or disb > 0):
            return 'receipt'
        if disb > receipt:
            return 'disbursement'
        return 'zero'

    def _get_net_amount(self, row: Any, is_bank: bool = True) -> float:
        def _safe_num(x: Any) -> float:
            try:
                if isinstance(x, (pd.Series, np.ndarray, list, tuple)):
                    v = pd.to_numeric(x, errors='coerce')
                    try:
                        return float(np.nansum(v))
                    except Exception:
                        return float(pd.Series(v).sum(skipna=True))
                v = pd.to_numeric(x, errors='coerce')
                return 0.0 if pd.isna(v) else float(v)
            except Exception:
                try:
                    return float(x)
                except Exception:
                    return 0.0

        if is_bank:
            rfield = self.config.BANK_RECEIPT_FIELD
            dfield = self.config.BANK_DISBURSEMENT_FIELD
        else:
            rfield = self.config.COMPANY_RECEIPT_FIELD
            dfield = self.config.COMPANY_DISBURSEMENT_FIELD

        try:
            if isinstance(row, pd.DataFrame):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            elif isinstance(row, pd.Series):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            elif isinstance(row, dict):
                receipt = abs(_safe_num(row.get(rfield, 0)))
                disb = abs(_safe_num(row.get(dfield, 0)))
            else:
                receipt = 0.0
                disb = 0.0
        except Exception:
            receipt = 0.0
            disb = 0.0
        return abs(receipt - disb)

    def _types_match(self, bank_tx: pd.Series, company_tx: pd.Series) -> bool:
        return self._get_transaction_type(bank_tx, True) == self._get_transaction_type(company_tx, False)

    def _amounts_match(self, amount1: float, amount2: float) -> bool:
        if abs(float(amount1)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)) or abs(float(amount2)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
            return False
        return abs(amount1 - amount2) <= self.config.AMOUNT_TOLERANCE

    # -------- Groupability and reservation guards (new) --------
    def _has_group_evidence(self, bank_tx: pd.Series = None, company_tx: pd.Series = None) -> bool:
        """Quickly checks whether a record likely belongs to a group (1:n or n:1).
        - For bank_tx provided: look for â‰¥2 company candidates within date window and txn_type whose sums can fit target amount within thresholds.
        - For company_tx provided: symmetric on bank side.
        """
        try:
            pct = float(getattr(self.config, 'MAX_GROUP_AMOUNT_DIFF_PCT', 0.0) or 0.0)
            max_size = int(getattr(self.config, 'AI_MAX_GROUP_SIZE', 5) or 5)
            date_range = int(getattr(self.config, 'MAX_GROUP_DATE_RANGE', 60) or 60)
            tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)

            if bank_tx is not None:
                target = self._get_net_amount(bank_tx, is_bank=True)
                if target < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                    return False
                bdate = bank_tx.get(self.config.BANK_DATE_FIELD)
                btype = self._get_transaction_type(bank_tx, is_bank=True)
                if pd.isna(bdate):
                    return False
                lower = bdate - pd.Timedelta(days=date_range)
                upper = bdate + pd.Timedelta(days=date_range)
                cand = self.company_df[
                    (~self.company_df.index.isin(self.matched_company_ids)) &
                    (self.company_df['txn_type'] == btype) &
                    (self.company_df[self.config.COMPANY_DATE_FIELD].between(lower, upper))
                ]
                if len(cand) < 2:
                    return False
                amts = sorted([self._get_net_amount(c, is_bank=False) for _, c in cand.iterrows()])
                # two-pointer near-sum quick check
                i, j = 0, len(amts) - 1
                while i < j:
                    s = amts[i] + amts[j]
                    diff = abs(s - target)
                    if (pct > 0 and diff / max(target, float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol):
                        return True
                    if s < target:
                        i += 1
                    else:
                        j -= 1
                # also check top-3 sum as a cheap heuristic
                topk = amts[-max_size:]
                for a in range(len(topk)):
                    for b in range(a + 1, len(topk)):
                        for c in range(b + 1, min(b + 2, len(topk))):
                            s = topk[a] + topk[b] + topk[c]
                            diff = abs(s - target)
                            if (pct > 0 and diff / max(target, float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol):
                                return True
                return False

            if company_tx is not None:
                target = self._get_net_amount(company_tx, is_bank=False)
                if target < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                    return False
                cdate = company_tx.get(self.config.COMPANY_DATE_FIELD)
                ctype = self._get_transaction_type(company_tx, is_bank=False)
                if pd.isna(cdate):
                    return False
                lower = cdate - pd.Timedelta(days=date_range)
                upper = cdate + pd.Timedelta(days=date_range)
                cand = self.bank_df[
                    (~self.bank_df.index.isin(self.matched_bank_ids)) &
                    (self.bank_df['txn_type'] == ctype) &
                    (self.bank_df[self.config.BANK_DATE_FIELD].between(lower, upper))
                ]
                if len(cand) < 2:
                    return False
                amts = sorted([self._get_net_amount(c, is_bank=True) for _, c in cand.iterrows()])
                i, j = 0, len(amts) - 1
                while i < j:
                    s = amts[i] + amts[j]
                    diff = abs(s - target)
                    if (pct > 0 and diff / max(target, float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol):
                        return True
                    if s < target:
                        i += 1
                    else:
                        j -= 1
                return False
        except Exception:
            return False

    def _is_part_of_better_group(self, bank_tx: pd.Series, company_tx: pd.Series) -> bool:
        """Exclusive-reservation check: would adding one more nearby candidate produce a closer sum?
        Returns True to defer a 1:1.
        """
        try:
            target = self._get_net_amount(bank_tx, is_bank=True)
            base = self._get_net_amount(company_tx, is_bank=False)
            if target < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)) or base < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                return False
            pct = float(getattr(self.config, 'MAX_GROUP_AMOUNT_DIFF_PCT', 0.0) or 0.0)
            tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)
            bdate = bank_tx.get(self.config.BANK_DATE_FIELD)
            btype = self._get_transaction_type(bank_tx, is_bank=True)
            if pd.isna(bdate):
                return False
            lower = bdate - pd.Timedelta(days=int(getattr(self.config, 'MAX_GROUP_DATE_RANGE', 60)))
            upper = bdate + pd.Timedelta(days=int(getattr(self.config, 'MAX_GROUP_DATE_RANGE', 60)))
            cands = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df['txn_type'] == btype) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(lower, upper))
            ]
            if company_tx.name in cands.index:
                cands = cands.drop(index=company_tx.name)
            if cands.empty:
                if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False):
                    try:
                        if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                            print("[Reservation] No nearby candidates found; proceed 1:1")
                        else:
                            self.logger.info("[Reservation] No nearby candidates found; proceed 1:1")
                    except Exception:
                        pass
                if getattr(self.config, 'ENABLE_RESERVATION_PROGRESS', False):
                    try:
                        print("[Reservation] No nearby candidates found; proceed 1:1")
                    except Exception:
                        pass
                return False
            iterable = cands.iterrows()
            if getattr(self.config, 'ENABLE_RESERVATION_PROGRESS', False):
                try:
                    from tqdm import tqdm
                    import sys
                    # persistent and sized nicely
                    iterable = tqdm(
                        iterable,
                        total=len(cands),
                        desc="Group reservation check",
                        leave=True,
                        dynamic_ncols=True,
                        mininterval=0.1,
                        file=sys.stdout,
                        ascii=True,
                        disable=False,
                    )
                except Exception:
                    pass
            reservations = [] if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False) else None
            if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False):
                try:
                    bank_id = bank_tx.get('UID', bank_tx.get(self.config.BANK_REF_FIELD, bank_tx.name))
                    c1_id = company_tx.get('UID', company_tx.get(self.config.COMPANY_REF_FIELD, company_tx.name))
                    msg = f"[Reservation] Start scan bank={bank_id} with base company={c1_id}; candidates={len(cands)}"
                    if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                        print(msg)
                    else:
                        self.logger.info(msg)
                except Exception:
                    pass
            # Always emit a visible print so progress is noticeable, even if logger output is muted
            if getattr(self.config, 'ENABLE_RESERVATION_PROGRESS', False):
                try:
                    print(f"[Reservation] Scanning {len(cands)} candidates for potential better group...")
                except Exception:
                    pass
            for _, c in iterable:
                s = base + self._get_net_amount(c, is_bank=False)
                diff = abs(s - target)
                if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False):
                    try:
                        c2_id = c.get('UID', c.get(self.config.COMPANY_REF_FIELD, c.name))
                        msg = (
                            f"[Reservation] bank={bank_id} c1={c1_id} c2={c2_id} "
                            f"base={base:.2f} add={self._get_net_amount(c, is_bank=False):.2f} "
                            f"target={target:.2f} diff={diff:.2f}"
                        )
                        if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                            print(msg)
                        else:
                            self.logger.info(msg)
                    except Exception:
                        pass
                if (pct > 0 and diff / max(target, float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol):
                    # Also require some semantic linkage
                    bank_desc = str(bank_tx.get(self.config.BANK_DESC_FIELD, '')).upper()
                    d1 = str(company_tx.get(self.config.COMPANY_DESC_FIELD, '')).upper()
                    d2 = str(c.get(self.config.COMPANY_DESC_FIELD, '')).upper()
                    name_sim = max(fuzz.token_set_ratio(bank_desc, d1), fuzz.token_set_ratio(bank_desc, d2)) / 100.0
                    if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False):
                        try:
                            msg = (
                                f"[Reservation] semantic link bank~(c1|c2) "
                                f"name_sim={name_sim:.2f} "
                                f"threshold={float(getattr(self.config, 'SEM_GROUP_SIM_THRESHOLD', 0.6)):.2f}"
                            )
                            if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                                print(msg)
                            else:
                                self.logger.info(msg)
                            if reservations is not None:
                                reservations.append({
                                    'bank_id': bank_id,
                                    'c1_id': c1_id,
                                    'c2_id': c2_id,
                                    'sum': round(s, 2),
                                    'target': round(target, 2),
                                    'diff': round(diff, 2),
                                    'name_sim': round(name_sim, 2),
                                })
                        except Exception:
                            pass
                    if name_sim >= float(getattr(self.config, 'SEM_GROUP_SIM_THRESHOLD', 0.6)):
                        if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False):
                            try:
                                if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                                    print("[Reservation] DEFER 1:1 due to potential better group with semantic+amount closeness")
                                else:
                                    self.logger.info("[Reservation] DEFER 1:1 due to potential better group with semantic+amount closeness")
                            except Exception:
                                pass
                        return True
            if getattr(self.config, 'ENABLE_RESERVATION_DEBUG', False) and reservations:
                try:
                    msg = f"[Reservation] Summary candidates considered: {reservations[:10]}{' ...' if len(reservations) > 10 else ''}"
                    if getattr(self.config, 'RESERVATION_LOG_TO_CONSOLE', False):
                        print(msg)
                    else:
                        self.logger.info(msg)
                except Exception:
                    pass
            if getattr(self.config, 'ENABLE_RESERVATION_PROGRESS', False):
                try:
                    print("[Reservation] Scan complete.")
                except Exception:
                    pass
            return False
        except Exception:
            return False

    # -------- Matching strategies --------
    def find_transaction_id_matches(self) -> List[MatchResult]:
        logger.info("Finding transaction ID matches...")
        results: List[MatchResult] = []
        # Reset AI decisions log for this stage run
        self._ai_decisions = []
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        for _, bank_tx in tqdm(unmatched_bank.iterrows(), desc="Transaction ID matching", total=len(unmatched_bank)):
            # Guard 2: potential group evidence
            if self._has_group_evidence(bank_tx=bank_tx):
                continue
            bank_txn_id = str(bank_tx.get(self.config.BANK_TXN_ID_FIELD, "")).strip()
            if not bank_txn_id or bank_txn_id.upper() == 'NONE':
                continue
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            if pd.isna(bank_date) or abs(float(bank_net)) < self.config.AMOUNT_TOLERANCE:
                continue
            date_lower = bank_date - pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            date_upper = bank_date + pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            matches = self.company_df[
                (self.company_df[self.config.COMPANY_DESC_FIELD].str.contains(bank_txn_id, case=False, na=False)) &
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(date_lower, date_upper)) &
                (self.company_df['net_amount'].between(bank_net - self.config.AMOUNT_TOLERANCE, bank_net + self.config.AMOUNT_TOLERANCE))
            ]
            for _, company_tx in matches.iterrows():
                if not self._types_match(bank_tx, company_tx):
                    continue
                company_net = self._get_net_amount(company_tx, is_bank=False)
                if not self._amounts_match(bank_net, company_net):
                    continue
                # Guard 3: reservation check
                if self._is_part_of_better_group(bank_tx, company_tx):
                    continue
                tx_type = self._get_transaction_type(bank_tx, is_bank=True)
                bank_dict = bank_tx.to_dict()
                company_dict = company_tx.to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                result = MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_dict['UID'],
                    match_score=95.0,
                    match_type='transaction_id',
                    transaction_type=tx_type,
                    amount_diff=round(abs(bank_net - company_net), 2),
                    date_diff=abs((bank_date - company_tx[self.config.COMPANY_DATE_FIELD]).days),
                    explanation=f"Matched on transaction ID {bank_txn_id} in description. Net amount: {bank_net:.2f} vs {company_net:.2f} ({tx_type})",
                    bank_data=bank_dict,
                    company_data=company_dict,
                )
                results.append(result)
                self.matched_company_ids.add(company_tx.name)
                if hasattr(self, 'matched_bank_ids'):
                    self.matched_bank_ids.add(bank_tx.name)
                break
        return results

    def find_bank_charges(self) -> List[MatchResult]:
        logger.info("Finding bank charges...")
        bank_charges: List[MatchResult] = []
        charge_keywords = [
            r"charge", r"fee", r"commission", r"service charge", r"interest", r"admin fee", r"bank charge",
            r"handling fee", r"transfer fee", r"maintenance", r"gst", r"vat", r"tax", r"levy", r"other transfer", r"processing", r"chq"
        ]
        charge_pattern = re.compile(r"|".join(charge_keywords), re.IGNORECASE)
        if not hasattr(self, 'matched_bank_ids'):
            self.matched_bank_ids = set()
        initial_count = len(self.matched_bank_ids)
        for idx, row in tqdm(self.bank_df.iterrows(), desc="Bank charges detection", total=len(self.bank_df), leave=True):
            desc = str(row.get(self.config.BANK_DESC_FIELD, ""))
            amount = float(row.get(self.config.BANK_DISBURSEMENT_FIELD, 0))
            receipt = float(row.get(self.config.BANK_RECEIPT_FIELD, 0))
            if (amount > 0 and amount < 100 and receipt == 0 and charge_pattern.search(desc)):
                row_dict = dict(row)
                if 'UID' not in row_dict and self.config.BANK_REF_FIELD in row_dict:
                    row_dict['UID'] = row_dict[self.config.BANK_REF_FIELD]
                match = MatchResult(
                    bank_tx_id=row_dict['UID'],
                    company_tx_id="N/A",  # Changed from None to "N/A"
                    match_score=80.0,
                    match_type="bank_charge",
                    transaction_type="disbursement",
                    amount_diff=float(row.get(self.config.BANK_DISBURSEMENT_FIELD, 0)),
                    date_diff=0,
                    explanation=f"Bank charge detected. Description: {row.get(self.config.BANK_DESC_FIELD, '')}",
                    bank_data=row_dict,
                    company_data={},
                )
                bank_charges.append(match)
                self.matched_bank_ids.add(idx)
        logger.debug(f"After bank charges detection: {len(self.matched_bank_ids)} matched (added {len(self.matched_bank_ids)-initial_count})")
        logger.info(f"Detected {len(bank_charges)} bank charges")
        return bank_charges

    def find_name_and_amount_matches(self) -> List[MatchResult]:
        logger.info("Finding name and amount matches...")
        results: List[MatchResult] = []
        bank_name_fields = [
            "Customer Reference", "Recipient Reference", "Other Payment Detail", "Sender Name", self.config.BANK_DESC_FIELD
        ]
        company_name_fields = ["Business Account Name", "Business Account", self.config.COMPANY_DESC_FIELD]
        if not hasattr(self, 'matched_bank_ids'):
            self.matched_bank_ids = set()
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        for _, bank_tx in tqdm(unmatched_bank.iterrows(), desc="Name and amount matching", total=len(unmatched_bank), leave=True):
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            if pd.isna(bank_date) or abs(float(bank_net)) < self.config.AMOUNT_TOLERANCE:
                continue
            date_lower = bank_date - pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            date_upper = bank_date + pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            potential_matches = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(date_lower, date_upper)) &
                (self.company_df['net_amount'].between(bank_net - self.config.AMOUNT_TOLERANCE, bank_net + self.config.AMOUNT_TOLERANCE))
            ]
            if len(potential_matches) == 0:
                continue
            best_match = None
            best_score = 0.0
            best_name_match = ""
            bank_names: List[str] = []
            for field in bank_name_fields:
                if field in bank_tx and bank_tx[field]:
                    value = str(bank_tx[field]).strip().upper()
                    if value and len(value) > 2:
                        bank_names.append(value)
            if not bank_names:
                continue
            for _, company_tx in potential_matches.iterrows():
                if not self._types_match(bank_tx, company_tx):
                    continue
                company_names: List[str] = []
                for field in company_name_fields:
                    if field in company_tx and company_tx[field]:
                        value = str(company_tx[field]).strip().upper()
                        if value and len(value) > 2:
                            company_names.append(value)
                if not company_names:
                    continue
                name_score = 0
                matched_name_pair = ""
                for bname in bank_names:
                    for cname in company_names:
                        if bname == cname:
                            current = 100
                            current_match = f"{bname} == {cname}"
                        elif bname in cname or cname in bname:
                            current = 90
                            current_match = f"{bname} in {cname}"
                        else:
                            current = fuzz.token_set_ratio(bname, cname)
                            current_match = f"{bname} ~ {cname} ({current}%)"
                        if current > name_score:
                            name_score = current
                            matched_name_pair = current_match
                date_diff = abs((bank_date - company_tx[self.config.COMPANY_DATE_FIELD]).days)
                date_score = max(0, 1 - (date_diff / self.config.DATE_TOLERANCE_DAYS))
                company_net = self._get_net_amount(company_tx, is_bank=False)
                amount_diff = abs(bank_net - company_net)
                amount_score = 1.0 if self.config.AMOUNT_TOLERANCE == 0 and amount_diff == 0 else max(0, 1 - (amount_diff / max(abs(bank_net), float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)))) / max(self.config.AMOUNT_TOLERANCE, 1e-9))
                combined = (name_score / 100 * 0.6) + (date_score * 0.2) + (amount_score * 0.2)
                if combined > best_score and name_score >= 70:
                    best_score = combined
                    best_match = company_tx
                    best_name_match = matched_name_pair
            if best_match is not None and best_score >= 0.7:
                # Guard 2: defer if group evidence exists for this bank record
                if self._has_group_evidence(bank_tx=bank_tx):
                    continue
                # Guard 3: exclusive reservation â€“ if pairing could be part of a better group, skip
                if self._is_part_of_better_group(bank_tx, best_match):
                    continue
                tx_type = self._get_transaction_type(bank_tx, is_bank=True)
                bank_dict = bank_tx.to_dict()
                company_dict = best_match.to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                company_net = self._get_net_amount(best_match, is_bank=False)
                date_diff = abs((bank_date - best_match[self.config.COMPANY_DATE_FIELD]).days)
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_dict['UID'],
                    match_score=best_score * 100,
                    match_type='name_and_amount',
                    transaction_type=tx_type,
                    amount_diff=round(abs(bank_net - company_net), 2),
                    date_diff=date_diff,
                    explanation=f"Name match: {best_name_match}. Net amount: {bank_net:.2f} vs {company_net:.2f} ({tx_type}). Date diff: {date_diff} days. Score: {best_score:.2f}",
                    bank_data=bank_dict,
                    company_data=company_dict,
                ))
                self.matched_company_ids.add(best_match.name)
                self.matched_bank_ids.add(bank_tx.name)
        logger.info(f"Found {len(results)} name and amount matches")
        return results

    def find_reverse_ce_gl_matches(self) -> List[MatchResult]:
        logger.info("Finding Reverse CE GL matches...")
        results: List[MatchResult] = []
        if 'Tran. Type' in self.company_df.columns:
            ce_gl = self.company_df[(self.company_df['Tran. Type'].isin(['Cash Entry', 'GL Entry'])) & (~self.company_df.index.isin(self.matched_company_ids))]
        else:
            ce_gl = self.company_df[~self.company_df.index.isin(self.matched_company_ids)]
            logger.info("'Tran. Type' column not found, processing all unmatched company transactions")
        if ce_gl.empty:
            return results
        doc_groups = ce_gl.groupby(self.config.COMPANY_REF_FIELD)
        for doc_ref, group in tqdm(doc_groups, desc="Reverse CE GL matching", total=len(doc_groups), leave=True):
            if pd.isna(doc_ref) or str(doc_ref).strip() == '':
                continue
            group_records = []
            for _, tx in group.iterrows():
                receipt_field = f"{self.config.COMPANY_RECEIPT_FIELD}_original"
                disb_field = f"{self.config.COMPANY_DISBURSEMENT_FIELD}_original"
                receipt_val = float(tx[receipt_field]) if receipt_field in tx and tx[receipt_field] is not None else float(tx.get(self.config.COMPANY_RECEIPT_FIELD, 0) or 0)
                disb_val = float(tx[disb_field]) if disb_field in tx and tx[disb_field] is not None else float(tx.get(self.config.COMPANY_DISBURSEMENT_FIELD, 0) or 0)
                has_neg = (receipt_val < 0) or (disb_val < 0)
                significant = receipt_val if abs(receipt_val) >= abs(disb_val) else disb_val
                group_records.append({
                    'tx': tx, 'receipt_val': receipt_val, 'disbursement_val': disb_val,
                    'significant_amount': significant, 'has_negative_value': has_neg, 'index': tx.name
                })
            negatives = [t for t in group_records if t['has_negative_value']]
            positives = [t for t in group_records if not t['has_negative_value'] and t['significant_amount'] != 0]
            for neg_tx in negatives:
                neg_amount = abs(neg_tx['significant_amount'])
                if neg_amount < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                    continue
                for pos_tx in list(positives):
                    pos_amount = abs(pos_tx['significant_amount'])
                    if abs(pos_amount - neg_amount) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                        neg_dict = neg_tx['tx'].to_dict(); pos_dict = pos_tx['tx'].to_dict()
                        if 'UID' not in neg_dict and self.config.COMPANY_REF_FIELD in neg_dict:
                            neg_dict['UID'] = neg_dict[self.config.COMPANY_REF_FIELD]
                        if 'UID' not in pos_dict and self.config.COMPANY_REF_FIELD in pos_dict:
                            pos_dict['UID'] = pos_dict[self.config.COMPANY_REF_FIELD]
                        neg_date = neg_tx['tx'].get(self.config.COMPANY_DATE_FIELD)
                        pos_date = pos_tx['tx'].get(self.config.COMPANY_DATE_FIELD)
                        date_diff = 0
                        if not pd.isna(neg_date) and not pd.isna(pos_date):
                            date_diff = abs((pd.to_datetime(neg_date) - pd.to_datetime(pos_date)).days)
                        tx_type = 'receipt' if abs(neg_tx['receipt_val']) >= abs(neg_tx['disbursement_val']) else 'disbursement'
                        explanation = (
                            f"Reverse CE/GL match: {neg_tx['tx'].get('Tran. Type', 'Unknown')} transactions with Document Ref '{doc_ref}'. "
                            f"Negative transaction: Receipt={neg_tx['receipt_val']:.2f}, Disbursement={neg_tx['disbursement_val']:.2f}. "
                            f"Positive transaction: Receipt={pos_tx['receipt_val']:.2f}, Disbursement={pos_tx['disbursement_val']:.2f}. "
                            f"Matched amounts: {neg_tx['significant_amount']:.2f} and {pos_tx['significant_amount']:.2f}"
                        )
                        results.append(MatchResult(
                            bank_tx_id=None,
                            company_tx_id=[neg_dict['UID'], pos_dict['UID']],
                            match_score=95.0,
                            match_type='reverse_ce_gl',
                            transaction_type=tx_type,
                            amount_diff=0.0,
                            date_diff=date_diff,
                            explanation=explanation,
                            bank_data={},
                            company_data=[neg_dict, pos_dict],
                        ))
                        self.matched_company_ids.add(neg_tx['index'])
                        self.matched_company_ids.add(pos_tx['index'])
                        # Avoid ambiguous truth value when comparing dicts containing pandas Series.
                        # Remove by unique index rather than object equality.
                        positives = [p for p in positives if p.get('index') != pos_tx.get('index')]
                        break
        logger.info(f"Found {len(results)} Reverse CE GL matches")
        return results

    def find_exact_matches(self) -> List[MatchResult]:
        logger.info("Finding enhanced 1:1 matches...")
        results: List[MatchResult] = []
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        for _, bank_tx in tqdm(unmatched_bank.iterrows(), desc="Exact matching", total=len(unmatched_bank)):
            # Guard 2: skip if likely groupable
            if self._has_group_evidence(bank_tx=bank_tx):
                continue
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            if pd.isna(bank_net) or pd.isna(bank_date) or abs(float(bank_net)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                continue
            company_candidates = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df['txn_type'] == self._get_transaction_type(bank_tx, is_bank=True)) &
                (self.company_df['net_amount'].abs() >= float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)))
            ]
            best_score = 0.0
            best_match = None
            best_expl = ""
            for _, company_tx in company_candidates.iterrows():
                amount_diff = abs(bank_net - company_tx['net_amount'])
                amount_score = 1.0 if self.config.AMOUNT_TOLERANCE == 0 and amount_diff == 0 else max(0, 1 - (amount_diff / max(abs(bank_net), float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)))) / max(self.config.AMOUNT_TOLERANCE, 1e-9))
                date_diff = abs((bank_date - company_tx[self.config.COMPANY_DATE_FIELD]).days)
                date_score = max(0, 1 - (date_diff / self.config.DATE_TOLERANCE_DAYS))
                ref_score = 0.0
                ref_expl = ""
                for ref_field in [self.config.BANK_REF_FIELD, self.config.BANK_TXN_ID_FIELD]:
                    bank_ref = str(bank_tx.get(ref_field, '')).strip()
                    company_ref = str(company_tx.get(self.config.COMPANY_REF_FIELD, '')).strip()
                    if bank_ref and company_ref:
                        if bank_ref == company_ref:
                            ref_score = float(getattr(self.config, 'REF_EXACT_SCORE', 1.0)); ref_expl = f"Exact reference match: {bank_ref}"; break
                        elif bank_ref in company_ref or company_ref in bank_ref:
                            ref_score = float(getattr(self.config, 'REF_PARTIAL_CONTAINS_SCORE', 0.9)); ref_expl = f"Partial reference match: {bank_ref} in {company_ref}"
                        elif len(bank_ref) > 5 and bank_ref[-6:] == company_ref[-6:]:
                            ref_score = float(getattr(self.config, 'REF_LAST6_SCORE', 0.8)); ref_expl = f"Last 6 digits match: {bank_ref[-6:]}"
                        elif fuzz.partial_ratio(bank_ref, company_ref) > int(getattr(self.config, 'REF_FUZZY_PARTIAL_RATIO_THRESHOLD', 90)):
                            ref_score = float(getattr(self.config, 'REF_FUZZY_SCORE', 0.8)); ref_expl = f"Fuzzy reference match: {bank_ref} ~ {company_ref}"
                desc_score = fuzz.token_set_ratio(str(bank_tx.get(self.config.BANK_DESC_FIELD, '')), str(company_tx.get(self.config.COMPANY_DESC_FIELD, ''))) / 100
                score = (
                    amount_score * self.config.AMOUNT_WEIGHT +
                    date_score * self.config.DATE_WEIGHT +
                    ref_score * self.config.REF_WEIGHT +
                    desc_score * self.config.DESC_WEIGHT
                )
                explanation = (
                    f"Amount score: {amount_score:.2f}, Date score: {date_score:.2f}, Ref score: {ref_score:.2f} ({ref_expl}), Desc score: {desc_score:.2f}, Total: {score:.2f}"
                )
                if score > best_score and score >= self.config.MIN_MATCH_SCORE:
                    best_score = score; best_match = company_tx; best_expl = explanation
            if best_match is not None and best_score >= 0.7:
                # Guard 3: reservation
                if self._is_part_of_better_group(bank_tx, best_match):
                    continue
                tx_type = self._get_transaction_type(bank_tx, is_bank=True)
                bank_dict = bank_tx.to_dict(); company_dict = best_match.to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_dict['UID'],
                    match_score=best_score * 100,
                    match_type='enhanced_1to1',
                    transaction_type=tx_type,
                    amount_diff=abs(bank_net - best_match['net_amount']),
                    date_diff=abs((bank_date - best_match[self.config.COMPANY_DATE_FIELD]).days),
                    explanation=best_expl,
                    bank_data=bank_dict,
                    company_data=company_dict,
                ))
                self.matched_company_ids.add(best_match.name)
                self.matched_bank_ids.add(bank_tx.name)
        logger.info(f"Found {len(results)} enhanced 1:1 matches")
        return results

    def find_hungarian_1to1_matches(self) -> List[MatchResult]:
        """Global optimal 1:1 matches using the Hungarian algorithm (if available).
        Falls back to mutual-best heuristic when SciPy is not installed.
        """
        logger.info("Finding Hungarian 1:1 matches...")
        results: List[MatchResult] = []
        import time
        t0 = time.time()

        # Config toggles with safe defaults
        use_rapidfuzz: bool = getattr(self.config, 'RAPIDFUZZ_ENABLED', True)
        top_k: int = int(getattr(self.config, 'HUNGARIAN_TOP_K', 10))
        log_stats: bool = getattr(self.config, 'HUNGARIAN_LOG_STATS', True)
        amount_gate: float = float(getattr(self.config, 'HUNGARIAN_AMOUNT_GATE', self.config.AMOUNT_TOLERANCE))

        # Text similarity with small LRU cache
        try:
            if use_rapidfuzz:
                from rapidfuzz import fuzz as rfuzz  # type: ignore
                def token_set_ratio(a: str, b: str) -> float:
                    return float(rfuzz.token_set_ratio(a, b))
            else:
                raise ImportError
        except Exception:
            def token_set_ratio(a: str, b: str) -> float:  # fallback to fuzzywuzzy
                return float(fuzz.token_set_ratio(a, b))

        from functools import lru_cache

        @lru_cache(maxsize=2048)
        def cached_token_set_ratio(a: str, b: str) -> float:
            return token_set_ratio(a, b)

        def compute_pair_score(bank_tx: pd.Series, company_tx: pd.Series) -> Tuple[float, Dict[str, Any]]:
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            comp_net = self._get_net_amount(company_tx, is_bank=False)
            if abs(float(bank_net)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)) or abs(float(comp_net)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                return 0.0, {}
            if not self._types_match(bank_tx, company_tx):
                return 0.0, {}
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            comp_date = company_tx.get(self.config.COMPANY_DATE_FIELD)
            if pd.isna(bank_date) or pd.isna(comp_date):
                return 0.0, {}
            amount_diff = abs(bank_net - comp_net)
            # Hard gate on amount difference to prune impossible pairs
            if amount_gate is not None and amount_diff > amount_gate:
                return 0.0, {}
            amount_score = 1.0 if self.config.AMOUNT_TOLERANCE == 0 and amount_diff == 0 else max(0, 1 - (amount_diff / max(abs(bank_net), 1)) / max(self.config.AMOUNT_TOLERANCE, 1e-9))
            date_diff = abs((bank_date - comp_date).days)
            date_score = max(0, 1 - (date_diff / self.config.DATE_TOLERANCE_DAYS))
            ref_score = 0.0
            ref_expl = ""
            for ref_field in [self.config.BANK_REF_FIELD, self.config.BANK_TXN_ID_FIELD]:
                bank_ref = str(bank_tx.get(ref_field, '')).strip()
                company_ref = str(company_tx.get(self.config.COMPANY_REF_FIELD, '')).strip()
                if bank_ref and company_ref:
                    if bank_ref == company_ref:
                        ref_score = float(getattr(self.config, 'REF_EXACT_SCORE', 1.0)); ref_expl = f"Exact reference match: {bank_ref}"; break
                    elif bank_ref in company_ref or company_ref in bank_ref:
                        ref_score = float(getattr(self.config, 'REF_PARTIAL_CONTAINS_SCORE', 0.9)); ref_expl = f"Partial reference match: {bank_ref} in {company_ref}"
                    elif len(bank_ref) > 5 and bank_ref[-6:] == company_ref[-6:]:
                        ref_score = float(getattr(self.config, 'REF_LAST6_SCORE', 0.8)); ref_expl = f"Last 6 digits match: {bank_ref[-6:]}"
                    elif fuzz.partial_ratio(bank_ref, company_ref) > int(getattr(self.config, 'REF_FUZZY_PARTIAL_RATIO_THRESHOLD', 90)):
                        ref_score = float(getattr(self.config, 'REF_FUZZY_SCORE', 0.8)); ref_expl = f"Fuzzy reference match: {bank_ref} ~ {company_ref}"
            desc_score = cached_token_set_ratio(
                str(bank_tx.get(self.config.BANK_DESC_FIELD, '')),
                str(company_tx.get(self.config.COMPANY_DESC_FIELD, '')),
            ) / 100.0
            score = (
                amount_score * self.config.AMOUNT_WEIGHT +
                date_score * self.config.DATE_WEIGHT +
                ref_score * self.config.REF_WEIGHT +
                desc_score * self.config.DESC_WEIGHT
            )
            meta = {
                'amount_diff': amount_diff,
                'date_diff': date_diff,
                'amount_score': amount_score,
                'date_score': date_score,
                'ref_score': ref_score,
                'ref_expl': ref_expl,
                'desc_score': desc_score,
                'score': score,
            }
            return score, meta

        unmatched_bank_df = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        unmatched_company_df = self.company_df[~self.company_df.index.isin(self.matched_company_ids)]
        if unmatched_bank_df.empty or unmatched_company_df.empty:
            return results

        if len(unmatched_bank_df) > self.config.MAX_TRANSACTIONS_TO_CONSIDER:
            unmatched_bank_df = unmatched_bank_df.sort_values(self.config.BANK_DATE_FIELD).tail(self.config.MAX_TRANSACTIONS_TO_CONSIDER)
        if len(unmatched_company_df) > self.config.MAX_TRANSACTIONS_TO_CONSIDER:
            unmatched_company_df = unmatched_company_df.sort_values(self.config.COMPANY_DATE_FIELD).tail(self.config.MAX_TRANSACTIONS_TO_CONSIDER)

        total_pairs_scored = 0
        total_pairs_kept = 0
        for tx_type in ['receipt', 'disbursement']:
            b_df = unmatched_bank_df[unmatched_bank_df['txn_type'] == tx_type]
            c_df = unmatched_company_df[unmatched_company_df['txn_type'] == tx_type]
            if b_df.empty or c_df.empty:
                continue
            # Use iterrows to avoid DataFrame slices on duplicate indices
            B = [row for _, row in b_df.iterrows()]
            C = [row for _, row in c_df.iterrows()]
            cost = np.full((len(B), len(C)), 1.0, dtype=float)
            meta_map: Dict[Tuple[int, int], Dict[str, Any]] = {}
            # Pre-score per bank row to select Top-K company candidates
            for i, btx in enumerate(B):
                prelim = []
                for j, ctx in enumerate(C):
                    score, meta = compute_pair_score(btx, ctx)
                    total_pairs_scored += 1
                    if meta and meta['date_diff'] <= self.config.DATE_TOLERANCE_DAYS and score > 0:
                        prelim.append((j, score, meta))
                # Keep only Top-K by score (or all if K<=0)
                if top_k and top_k > 0 and len(prelim) > top_k:
                    prelim.sort(key=lambda x: x[1], reverse=True)
                    prelim = prelim[:top_k]
                for j, score, meta in prelim:
                    total_pairs_kept += 1
                    cost[i, j] = 1.0 - max(0.0, min(1.0, score))
                    meta_map[(i, j)] = meta
            assignments: List[Tuple[int, int]] = []
            try:
                from scipy.optimize import linear_sum_assignment  # type: ignore
                row_ind, col_ind = linear_sum_assignment(cost)
                assignments = [(int(r), int(c)) for r, c in zip(row_ind, col_ind)]
            except Exception as e:
                logger.debug(f"SciPy not available or failed ({e}); falling back to mutual-best heuristic for Hungarian step.")
                best_for_row: Dict[int, int] = {}
                best_for_col: Dict[int, int] = {}
                for i in range(len(B)):
                    j_best = int(np.argmin(cost[i, :])) if cost.shape[1] > 0 else -1
                    best_for_row[i] = j_best
                for j in range(len(C)):
                    i_best = int(np.argmin(cost[:, j])) if cost.shape[0] > 0 else -1
                    best_for_col[j] = i_best
                for i, j in best_for_row.items():
                    if j >= 0 and best_for_col.get(j, -1) == i:
                        assignments.append((i, j))

            for i, j in assignments:
                meta = meta_map.get((i, j))
                if not meta:
                    continue
                if meta['score'] < self.config.MIN_MATCH_SCORE:
                    continue
                btx = B[i]; ctx = C[j]
                bank_dict = btx.to_dict(); comp_dict = ctx.to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in comp_dict and self.config.COMPANY_REF_FIELD in comp_dict:
                    comp_dict['UID'] = comp_dict[self.config.COMPANY_REF_FIELD]
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=comp_dict['UID'],
                    match_score=meta['score'] * 100,
                    match_type='hungarian_1to1',
                    transaction_type=tx_type,
                    amount_diff=round(float(meta['amount_diff']), 2),
                    date_diff=int(meta['date_diff']),
                    explanation=f"Hungarian 1:1 | Amount {meta['amount_score']:.2f}, Date {meta['date_score']:.2f}, Ref {meta['ref_score']:.2f} ({meta['ref_expl']}), Desc {meta['desc_score']:.2f} => {meta['score']:.2f}",
                    bank_data=bank_dict,
                    company_data=comp_dict,
                ))
                self.matched_bank_ids.add(btx.name)
                self.matched_company_ids.add(ctx.name)

        t1 = time.time()
        if log_stats:
            logger.info(
                f"Hungarian 1:1: {len(results)} matches | pairs scored={total_pairs_scored}, kept={total_pairs_kept}, time={t1 - t0:.2f}s"
            )
        else:
            logger.info(f"Found {len(results)} Hungarian 1:1 matches")
        return results

    def find_amount_date_matches(self) -> List[MatchResult]:
        logger.info("Finding amount and date matches...")
        results: List[MatchResult] = []
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        for _, bank_tx in tqdm(unmatched_bank.iterrows(), desc="Amount+Date matching", total=len(unmatched_bank), leave=True):
            # Guard 2: possible group
            if self._has_group_evidence(bank_tx=bank_tx):
                continue
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            if pd.isna(bank_date) or abs(float(bank_net)) < self.config.AMOUNT_TOLERANCE:
                continue
            date_lower = bank_date - pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            date_upper = bank_date + pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            candidates = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(date_lower, date_upper)) &
                (abs(self.company_df['net_amount'] - bank_net) <= self.config.AMOUNT_TOLERANCE)
            ]
            if len(candidates) == 0:
                continue
            best_match = None
            best_date_diff = float('inf')
            for _, company_tx in candidates.iterrows():
                date_diff = abs((bank_date - company_tx[self.config.COMPANY_DATE_FIELD]).days)
                if date_diff < best_date_diff:
                    best_date_diff = date_diff
                    best_match = company_tx
            if best_match is not None:
                tx_type = self._get_transaction_type(bank_tx, is_bank=True)
                bank_dict = bank_tx.to_dict(); company_dict = best_match.to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                date_score = max(0, 1 - (best_date_diff / self.config.DATE_TOLERANCE_DAYS))
                match_score = 85 + (date_score * 10)
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_dict['UID'],
                    match_score=match_score,
                    match_type='amount_date',
                    transaction_type=tx_type,
                    amount_diff=abs(bank_net - best_match['net_amount']),
                    date_diff=best_date_diff,
                    explanation=f"Exact amount match ({bank_net:.2f}) with date difference of {best_date_diff} days",
                    bank_data=bank_dict,
                    company_data=company_dict,
                ))
                self.matched_company_ids.add(best_match.name)
                if hasattr(self, 'matched_bank_ids'):
                    self.matched_bank_ids.add(bank_tx.name)
        logger.info(f"Found {len(results)} amount and date matches")
        return results

    def find_fuzzy_matches(self) -> List[MatchResult]:
        logger.info("Finding fuzzy matches...")
        results: List[MatchResult] = []
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)] if hasattr(self, 'matched_bank_ids') else self.bank_df
        for _, bank_tx in tqdm(unmatched_bank.iterrows(), desc="Fuzzy matching", total=len(unmatched_bank)):
            # Guard 2: group evidence
            if self._has_group_evidence(bank_tx=bank_tx):
                continue
            bank_net = self._get_net_amount(bank_tx, is_bank=True)
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            bank_desc = str(bank_tx.get(self.config.BANK_DESC_FIELD, "")).upper()
            if pd.isna(bank_net) or pd.isna(bank_date) or abs(float(bank_net)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                continue
            date_lower = bank_date - pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            date_upper = bank_date + pd.Timedelta(days=self.config.DATE_TOLERANCE_DAYS)
            potential = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(date_lower, date_upper)) &
                (self.company_df['net_amount'].between(bank_net - self.config.AMOUNT_TOLERANCE, bank_net + self.config.AMOUNT_TOLERANCE))
            ]
            if len(potential) == 0:
                continue
            best_match = None
            best_score = -1
            for _, company_tx in potential.iterrows():
                if not self._types_match(bank_tx, company_tx):
                    continue
                company_desc = str(company_tx.get(self.config.COMPANY_DESC_FIELD, "")).upper()
                score = fuzz.token_set_ratio(bank_desc, company_desc)
                company_net = self._get_net_amount(company_tx, is_bank=False)
                if score > best_score and score >= self.config.MIN_FUZZY_SCORE:
                    best_score = score
                    best_match = {'tx': company_tx, 'score': score, 'amount_diff': round(abs(bank_net - company_net), 2), 'date_diff': abs((bank_date - company_tx[self.config.COMPANY_DATE_FIELD]).days)}
            if best_match:
                if self._is_part_of_better_group(bank_tx, best_match['tx']):
                    continue
                tx_type = self._get_transaction_type(bank_tx, is_bank=True)
                bank_dict = bank_tx.to_dict(); company_dict = best_match['tx'].to_dict()
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_dict['UID'],
                    match_score=best_match['score'],
                    match_type='fuzzy',
                    transaction_type=tx_type,
                    amount_diff=best_match['amount_diff'],
                    date_diff=best_match['date_diff'],
                    explanation=(f"Fuzzy match with score {best_match['score']}/100. Net amount: {bank_net:.2f} vs {self._get_net_amount(best_match['tx'], is_bank=False):.2f} ({tx_type})"),
                    bank_data=bank_dict,
                    company_data=company_dict,
                ))
                self.matched_company_ids.add(best_match['tx'].name)
                if hasattr(self, 'matched_bank_ids'):
                    self.matched_bank_ids.add(bank_tx.name)
        return results

    def find_group_matches(self) -> List[MatchResult]:
        logger.info("Finding group matches...")
        results: List[MatchResult] = []
        # Prevent accidental duplicate execution within a single run
        if getattr(self, "_group_stage_executed", False):
            logger.warning("find_group_matches() called more than once in the same run; skipping to avoid duplicates")
            return results
        setattr(self, "_group_stage_executed", True)
        logger.debug("Group stage entry: starting semantic and fallback group matching")
        # 1) Semantic-first grouping (lightweight, non-brute-force)
        if getattr(self.config, 'ENABLE_SEMANTIC_GROUPS', True):
            results.extend(self._find_semantic_group_matches())
        # 2) Fallback to existing group search (only if semantic didn't find enough)
        if len(results) < 5:  # Only run traditional fallback if semantic found few matches
            results.extend(self._find_one_to_many_matches())
            results.extend(self._find_many_to_one_matches())
        logger.info(f"Found {len(results)} group matches")
        logger.debug("Group stage exit: completed group matching")
        return results

    def _semantic_text(self, tx: pd.Series, is_bank: bool) -> str:
        desc_field = self.config.BANK_DESC_FIELD if is_bank else self.config.COMPANY_DESC_FIELD
        ref_field = self.config.BANK_REF_FIELD if is_bank else self.config.COMPANY_REF_FIELD
        desc = str(tx.get(desc_field, ""))
        ref = str(tx.get(ref_field, ""))
        return (desc + " " + ref).upper().strip()

    def _find_semantic_group_matches(self) -> List[MatchResult]:
        """Semantic-driven grouping that avoids full combinatorics.
        Strategy:
        - For each unmatched bank tx, gather top-K company candidates by semantic similarity (desc+ref) within date window and same txn_type.
        - Greedily assemble up to SEM_GROUP_MAX_SIZE candidates whose cumulative amount approaches the bank amount within tolerance, preferring higher semantic scores.
        - Mirror for unmatched company txs vs bank txs.
        """
        results: List[MatchResult] = []
        # Local import to avoid global dependency
        try:
            from tqdm import tqdm
        except Exception:
            def tqdm(x, **kwargs):
                return x
        if not hasattr(self, 'matched_bank_ids'):
            self.matched_bank_ids = set()
        if not hasattr(self, 'matched_company_ids'):
            self.matched_company_ids = set()

        sim_thr = float(getattr(self.config, 'SEM_GROUP_SIM_THRESHOLD', 0.60))
        topk = int(getattr(self.config, 'SEM_GROUP_TOPK', 8))
        max_size = int(getattr(self.config, 'SEM_GROUP_MAX_SIZE', 5))
        date_win = int(getattr(self.config, 'MAX_GROUP_DATE_RANGE', 60))
        pct = float(getattr(self.config, 'MAX_GROUP_AMOUNT_DIFF_PCT', 0.0))
        tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0))

        # --- n:1 (bank target, company parts)
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self.matched_bank_ids)]
        for b_idx, btx in tqdm(unmatched_bank.iterrows(), total=len(unmatched_bank), desc="Semantic n:1 (AI)", leave=False):
            b_amount = self._get_net_amount(btx, is_bank=True)
            if abs(float(b_amount)) < float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)):
                continue
            b_date = btx.get(self.config.BANK_DATE_FIELD)
            if pd.isna(b_date):
                continue
            b_type = self._get_transaction_type(btx, is_bank=True)
            lower = b_date - pd.Timedelta(days=date_win)
            upper = b_date + pd.Timedelta(days=date_win)
            cands = self.company_df[
                (~self.company_df.index.isin(self.matched_company_ids)) &
                (self.company_df['txn_type'] == b_type) &
                (self.company_df[self.config.COMPANY_DATE_FIELD].between(lower, upper))
            ]
            if cands.empty:
                continue
            b_text = self._semantic_text(btx, is_bank=True)
            scored = []
            for c_idx, ctx in cands.iterrows():
                c_text = self._semantic_text(ctx, is_bank=False)
                sim = fuzz.token_set_ratio(b_text, c_text) / 100.0
                if sim >= sim_thr:
                    amt = self._get_net_amount(ctx, is_bank=False)
                    scored.append((sim, c_idx, ctx, amt))
            if not scored:
                continue
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = scored[:topk]
            # Greedy accumulate by sim order
            chosen = []
            total = 0.0
            for sim, c_idx, ctx, amt in scored:
                if len(chosen) >= max_size:
                    break
                candidate_total = total + amt
                diff = abs(candidate_total - b_amount)
                if (pct > 0 and diff / max(abs(b_amount), float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol) or (abs(candidate_total) <= abs(b_amount) and len(chosen) + 1 < max_size):
                    chosen.append((sim, c_idx, ctx, amt))
                    total += amt
                # Early stop if perfect
                if abs(total - b_amount) <= max(tol, pct * max(abs(b_amount), float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01)))):
                    break
            # Validate
            if len(chosen) >= 2:
                diff = abs(total - b_amount)
                if (pct > 0 and diff / max(abs(b_amount), float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))) <= pct) or (tol > 0 and diff <= tol):
                    bank_dict = btx.to_dict(); bank_id = bank_dict.get('UID', bank_dict.get(self.config.BANK_REF_FIELD, b_idx))
                    comp_dicts = [ctx.to_dict() for _, c_idx, ctx, _ in chosen]
                    comp_ids = [d.get('UID', d.get(self.config.COMPANY_REF_FIELD, idx)) for (_, idx, ctx, _), d in zip(chosen, comp_dicts)]
                    avg_sim = sum(s for s, *_ in chosen) / len(chosen)
                    results.append(MatchResult(
                        bank_tx_id=bank_id,
                        company_tx_id=comp_ids,
                        match_score=int(100 * avg_sim),
                        match_type='semantic_group_n_to_1',
                        transaction_type=b_type,
                        amount_diff=round(diff, 2),
                        date_diff=0,
                        explanation=f"Semantic group n:1 via top-{len(chosen)} candidates; avg_sim={avg_sim:.2f}",
                        bank_data=btx.to_dict(),
                        company_data=comp_dicts,
                    ))
                    # Reserve
                    if hasattr(self, 'matched_bank_ids'):
                        self.matched_bank_ids.add(b_idx)
                    if hasattr(self, 'matched_company_ids'):
                        for _, c_idx, _, _ in chosen:
                            self.matched_company_ids.add(c_idx)

        # --- 1:n (company target, bank parts)
        unmatched_company = self.company_df[~self.company_df.index.isin(self.matched_company_ids)]
        for c_idx, ctx in tqdm(unmatched_company.iterrows(), total=len(unmatched_company), desc="Semantic 1:n (AI)", leave=False):
            c_amount = self._get_net_amount(ctx, is_bank=False)
            if abs(float(c_amount)) < 0.01:
                continue
            c_date = ctx.get(self.config.COMPANY_DATE_FIELD)
            if pd.isna(c_date):
                continue
            c_type = self._get_transaction_type(ctx, is_bank=False)
            lower = c_date - pd.Timedelta(days=date_win)
            upper = c_date + pd.Timedelta(days=date_win)
            b_cands = self.bank_df[
                (~self.bank_df.index.isin(self.matched_bank_ids)) &
                (self.bank_df['txn_type'] == c_type) &
                (self.bank_df[self.config.BANK_DATE_FIELD].between(lower, upper))
            ]
            if b_cands.empty:
                continue
            c_text = self._semantic_text(ctx, is_bank=False)
            scored = []
            for b2_idx, b2tx in b_cands.iterrows():
                b_text = self._semantic_text(b2tx, is_bank=True)
                sim = fuzz.token_set_ratio(c_text, b_text) / 100.0
                if sim >= sim_thr:
                    amt = self._get_net_amount(b2tx, is_bank=True)
                    scored.append((sim, b2_idx, b2tx, amt))
            if not scored:
                continue
            scored.sort(key=lambda x: x[0], reverse=True)
            scored = scored[:topk]
            chosen = []
            total = 0.0
            for sim, b2_idx, b2tx, amt in scored:
                if len(chosen) >= max_size:
                    break
                candidate_total = total + amt
                diff = abs(candidate_total - c_amount)
                if (pct > 0 and diff / max(abs(c_amount), 0.01) <= pct) or (tol > 0 and diff <= tol) or (abs(candidate_total) <= abs(c_amount) and len(chosen) + 1 < max_size):
                    chosen.append((sim, b2_idx, b2tx, amt))
                    total += amt
                if abs(total - c_amount) <= max(tol, pct * max(abs(c_amount), 0.01)):
                    break
            if len(chosen) >= 2:
                diff = abs(total - c_amount)
                if (pct > 0 and diff / max(abs(c_amount), 0.01) <= pct) or (tol > 0 and diff <= tol):
                    company_dict = ctx.to_dict(); company_id = company_dict.get('UID', company_dict.get(self.config.COMPANY_REF_FIELD, c_idx))
                    bank_dicts = [b2tx.to_dict() for _, b2_idx, b2tx, _ in chosen]
                    bank_ids = [d.get('UID', d.get(self.config.BANK_REF_FIELD, idx)) for (_, idx, b2tx, _), d in zip(chosen, bank_dicts)]
                    avg_sim = sum(s for s, *_ in chosen) / len(chosen)
                    results.append(MatchResult(
                        bank_tx_id=bank_ids,
                        company_tx_id=company_id,
                        match_score=int(100 * avg_sim),
                        match_type='semantic_group_1_to_n',
                        transaction_type=c_type,
                        amount_diff=round(diff, 2),
                        date_diff=0,
                        explanation=f"Semantic group 1:n via top-{len(chosen)} candidates; avg_sim={avg_sim:.2f}",
                        bank_data=bank_dicts,
                        company_data=ctx.to_dict(),
                    ))
                    if hasattr(self, 'matched_company_ids'):
                        self.matched_company_ids.add(c_idx)
                    if hasattr(self, 'matched_bank_ids'):
                        for _, b2_idx, _, _ in chosen:
                            self.matched_bank_ids.add(b2_idx)
        return results

    def _find_one_to_many_matches(self) -> List[MatchResult]:
        results: List[MatchResult] = []
        if not hasattr(self, 'matched_bank_ids'):
            self.matched_bank_ids = set()
        local_matched_bank_ids = set(self.matched_bank_ids)
        local_matched_company_ids = set(self.matched_company_ids)
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(local_matched_bank_ids)]
        significant_bank = unmatched_bank[unmatched_bank['net_amount'] > 0.01]
        if significant_bank.empty or self.company_df.empty:
            return results
        logger.info(f"Processing {len(significant_bank)} bank transactions for 1:n matching (fallback)")
        for _, bank_tx in tqdm(significant_bank.iterrows(), desc="Fallback 1:n (traditional)", total=len(significant_bank)):
            # Skip if this bank UID has become matched earlier in this loop
            if bank_tx.name in local_matched_bank_ids:
                continue
            # Recompute unmatched company set per-iteration to avoid reusing UIDs
            unmatched_company = self.company_df[~self.company_df.index.isin(local_matched_company_ids)]
            if unmatched_company.empty:
                break
            bank_date = bank_tx.get(self.config.BANK_DATE_FIELD)
            bank_amount = self._get_net_amount(bank_tx, is_bank=True)
            bank_type = self._get_transaction_type(bank_tx, is_bank=True)
            if pd.isna(bank_date) or bank_amount < 0.01:
                continue
            date_lower = bank_date - pd.Timedelta(days=self.config.MAX_GROUP_DATE_RANGE)
            date_upper = bank_date + pd.Timedelta(days=self.config.MAX_GROUP_DATE_RANGE)
            date_filtered = unmatched_company[(unmatched_company[self.config.COMPANY_DATE_FIELD].between(date_lower, date_upper)) & (unmatched_company['txn_type'] == bank_type)]
            if date_filtered.empty or len(date_filtered) < 2:
                continue
            if len(date_filtered) > self.config.MAX_TRANSACTIONS_TO_CONSIDER:
                date_filtered = date_filtered.sort_values(by='net_amount', ascending=False).head(self.config.MAX_TRANSACTIONS_TO_CONSIDER)
            best_group = None
            best_score = 0.0
            max_group_size = min(self.config.MAX_GROUP_SIZE, 3, len(date_filtered))
            for group_size in range(2, max_group_size + 1):
                combo_count = 0
                for combo in combinations(date_filtered.index, group_size):
                    combo_count += 1
                    if combo_count > self.config.MAX_COMBINATIONS_TO_TRY:
                        break
                    group_txs = date_filtered.loc[list(combo)]
                    group_amount = sum(self._get_net_amount(group_txs.loc[idx], is_bank=False) for idx in combo)
                    amount_diff = abs(bank_amount - group_amount)
                    amount_diff_pct = amount_diff / max(bank_amount, 0.01)
                    if amount_diff_pct > self.config.MAX_GROUP_AMOUNT_DIFF_PCT:
                        continue
                    amount_score = max(0, 1 - amount_diff / max(bank_amount, 0.01))
                    # Normalize dates (handle duplicate-index returning Series)
                    def _to_ts(x):
                        try:
                            if isinstance(x, (pd.Series, list, tuple, np.ndarray)):
                                s = pd.to_datetime(pd.Series(list(x) if not isinstance(x, pd.Series) else x), errors='coerce')
                                return s.min()
                            return pd.to_datetime(x, errors='coerce')
                        except Exception:
                            return pd.NaT
                    group_dates = [_to_ts(group_txs.loc[idx, self.config.COMPANY_DATE_FIELD]) for idx in combo]
                    date_diffs = []
                    for d in group_dates:
                        try:
                            if pd.isna(d) or pd.isna(bank_date):
                                continue
                            date_diffs.append(abs((bank_date - d).days))
                        except Exception:
                            continue
                    if not date_diffs:
                        date_diffs = [self.config.MAX_GROUP_DATE_RANGE]
                    avg_date_diff = sum(date_diffs) / len(date_diffs)
                    date_score = max(0, 1 - avg_date_diff / self.config.MAX_GROUP_DATE_RANGE)
                    bank_desc = str(bank_tx.get(self.config.BANK_DESC_FIELD, "")).upper()
                    group_descs = [str(group_txs.loc[idx, self.config.COMPANY_DESC_FIELD]) for idx in combo]
                    desc_scores = [fuzz.token_set_ratio(bank_desc, d) / 100 for d in group_descs]
                    avg_desc_score = sum(desc_scores) / len(desc_scores)
                    score = (amount_score * 0.6) + (date_score * 0.2) + (avg_desc_score * 0.2)
                    if score > best_score and amount_score > 0.95:
                        best_score = score
                        best_group = {'indices': list(combo), 'txs': group_txs, 'amount': group_amount, 'score': score, 'amount_diff': amount_diff, 'date_diff': avg_date_diff}
            if best_group and best_score >= self.config.MIN_GROUP_SCORE / 100:
                bank_dict = bank_tx.to_dict()
                company_dicts = [best_group['txs'].loc[idx].to_dict() for idx in best_group['indices']]
                if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                    bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                for i, company_dict in enumerate(company_dicts):
                    if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                        company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                company_tx_ids = [d['UID'] for d in company_dicts]
                results.append(MatchResult(
                    bank_tx_id=bank_dict['UID'],
                    company_tx_id=company_tx_ids,
                    match_score=best_score * 100,
                    match_type='group_1_to_n',
                    transaction_type=bank_type,
                    amount_diff=best_group['amount_diff'],
                    date_diff=int(best_group['date_diff']),
                    explanation=(f"Group match: 1 bank transaction matches {len(best_group['indices'])} company transactions. Bank amount: {bank_amount:.2f}, Group amount: {best_group['amount']:.2f}, Diff: {best_group['amount_diff']:.2f}, Score: {best_score:.2f}"),
                    bank_data=bank_dict,
                    company_data=company_dicts,
                ))
                if hasattr(self, 'matched_bank_ids'):
                    self.matched_bank_ids.add(bank_tx.name)
                self.matched_company_ids.update(best_group['indices'])
                # Update local snapshots immediately so subsequent iterations exclude these UIDs
                local_matched_bank_ids.add(bank_tx.name)
                local_matched_company_ids.update(best_group['indices'])
        return results

    def _find_many_to_one_matches(self) -> List[MatchResult]:
        """Find groups of bank transactions that sum to a single company transaction (n:1)."""
        results: List[MatchResult] = []
        if not hasattr(self, 'matched_bank_ids'):
            self.matched_bank_ids = set()
        # Work on local snapshots of matched sets
        local_matched_bank_ids = set(self.matched_bank_ids)
        local_matched_company_ids = set(self.matched_company_ids)

        unmatched_bank = self.bank_df[~self.bank_df.index.isin(local_matched_bank_ids)]
        unmatched_company = self.company_df[~self.company_df.index.isin(local_matched_company_ids)]
        significant_company = unmatched_company[unmatched_company['net_amount'] > 0.01]
        if unmatched_bank.empty or significant_company.empty:
            return results
        logger.info(f"Processing {len(significant_company)} company transactions for n:1 matching (fallback)")

        for _, company_tx in tqdm(significant_company.iterrows(), desc="Fallback n:1 (traditional)", total=len(significant_company)):
            # Skip if this company UID has become matched earlier in this loop
            if company_tx.name in local_matched_company_ids:
                continue
            # Recompute unmatched bank set per-iteration to avoid reusing UIDs
            unmatched_bank = self.bank_df[~self.bank_df.index.isin(local_matched_bank_ids)]
            if unmatched_bank.empty:
                break
            comp_date = company_tx.get(self.config.COMPANY_DATE_FIELD)
            comp_amount = self._get_net_amount(company_tx, is_bank=False)
            comp_type = self._get_transaction_type(company_tx, is_bank=False)
            if pd.isna(comp_date) or comp_amount < 0.01:
                continue
            date_lower = comp_date - pd.Timedelta(days=self.config.MAX_GROUP_DATE_RANGE)
            date_upper = comp_date + pd.Timedelta(days=self.config.MAX_GROUP_DATE_RANGE)
            date_filtered = unmatched_bank[(unmatched_bank[self.config.BANK_DATE_FIELD].between(date_lower, date_upper)) & (unmatched_bank['txn_type'] == comp_type)]
            if date_filtered.empty or len(date_filtered) < 2:
                continue
            if len(date_filtered) > self.config.MAX_TRANSACTIONS_TO_CONSIDER:
                date_filtered = date_filtered.sort_values(by='net_amount', ascending=False).head(self.config.MAX_TRANSACTIONS_TO_CONSIDER)

            best_group = None
            best_score = 0.0
            max_group_size = min(self.config.MAX_GROUP_SIZE, 3, len(date_filtered))
            for group_size in range(2, max_group_size + 1):
                combo_count = 0
                for combo in combinations(date_filtered.index, group_size):
                    combo_count += 1
                    if combo_count > self.config.MAX_COMBINATIONS_TO_TRY:
                        break
                    group_txs = date_filtered.loc[list(combo)]
                    group_amount = sum(self._get_net_amount(group_txs.loc[idx], is_bank=True) for idx in combo)
                    amount_diff = abs(group_amount - comp_amount)
                    amount_diff_pct = amount_diff / max(comp_amount, 0.01)
                    if amount_diff_pct > self.config.MAX_GROUP_AMOUNT_DIFF_PCT:
                        continue
                    amount_score = max(0, 1 - amount_diff / max(comp_amount, 0.01))
                    comp_desc = str(company_tx.get(self.config.COMPANY_DESC_FIELD, "")).upper()
                    group_dates = [group_txs.loc[idx, self.config.BANK_DATE_FIELD] for idx in combo]
                    date_diffs = [abs((comp_date - d).days) for d in group_dates]
                    avg_date_diff = sum(date_diffs) / len(date_diffs)
                    date_score = max(0, 1 - avg_date_diff / self.config.MAX_GROUP_DATE_RANGE)
                    group_descs = [str(group_txs.loc[idx, self.config.BANK_DESC_FIELD]) for idx in combo]
                    desc_scores = [fuzz.token_set_ratio(comp_desc, d) / 100 for d in group_descs]
                    avg_desc_score = sum(desc_scores) / len(desc_scores)
                    score = (amount_score * 0.6) + (date_score * 0.2) + (avg_desc_score * 0.2)
                    if score > best_score and amount_score > 0.95:
                        best_score = score
                        best_group = {'indices': list(combo), 'txs': group_txs, 'amount': group_amount, 'score': score, 'amount_diff': amount_diff, 'date_diff': avg_date_diff}

            if best_group and best_score >= self.config.MIN_GROUP_SCORE / 100:
                company_dict = company_tx.to_dict()
                if 'UID' not in company_dict and self.config.COMPANY_REF_FIELD in company_dict:
                    company_dict['UID'] = company_dict[self.config.COMPANY_REF_FIELD]
                bank_dicts = [best_group['txs'].loc[idx].to_dict() for idx in best_group['indices']]
                for i, bank_dict in enumerate(bank_dicts):
                    if 'UID' not in bank_dict and self.config.BANK_REF_FIELD in bank_dict:
                        bank_dict['UID'] = bank_dict[self.config.BANK_REF_FIELD]
                bank_tx_ids = [d.get('UID') for d in bank_dicts]
                tx_type = comp_type
                results.append(MatchResult(
                    bank_tx_id=bank_tx_ids,
                    company_tx_id=company_dict['UID'],
                    match_score=best_score * 100,
                    match_type='group_n_to_1',
                    transaction_type=tx_type,
                    amount_diff=best_group['amount_diff'],
                    date_diff=int(best_group['date_diff']),
                    explanation=(f"Group match: {len(best_group['indices'])} bank transactions match 1 company transaction. Group amount: {best_group['amount']:.2f}, Company amount: {comp_amount:.2f}, Diff: {best_group['amount_diff']:.2f}, Score: {best_score:.2f}"),
                    bank_data=bank_dicts,
                    company_data=company_dict,
                ))
                # Update matched sets
                for bid in best_group['indices']:
                    self.matched_bank_ids.add(bid)
                self.matched_company_ids.add(company_tx.name)
                # Update local snapshots immediately so subsequent iterations exclude these UIDs
                local_matched_bank_ids.update(best_group['indices'])
                local_matched_company_ids.add(company_tx.name)
        return results

class _BaseUtils:
    pass
# =============================
# Unified Reconciler (composition-only)
# =============================
class UnifiedReconciler:
    """
    Orchestrates the full reconciliation pipeline in two stages:
    1) Traditional matching using EnhancedReconciler
    2) AI verification and semantic matching (strictly at the end)

    No inheritance is used; this class composes existing reconcilers and orders steps.
    """

    def __init__(self, config: Optional[UnifiedConfig] = None):
        self.config = config or UnifiedConfig()
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(getattr(logging, self.config.LOG_LEVEL, logging.INFO))
        self.bank_df: Optional[pd.DataFrame] = None
        self.company_df: Optional[pd.DataFrame] = None
        self.results: List[MatchResult] = []
        self._matched_bank_ids: set = set()
        self._matched_company_ids: set = set()
        # Collect per-candidate AI decisions (accepted and rejected) with explanations
        self._ai_decisions: List[Dict[str, Any]] = []
        
        # Initialize semantic cache for AI calls
        self._semantic_cache = {}
        # Budget: cap remote AI calls per run
        self._ai_api_calls = 0
        # Stateful model rotation index for OpenRouter models
        self._model_rotation_index = 0
        # Token accounting (LLM usage)
        self._token_in_total: int = 0
        self._token_out_total: int = 0
        self._token_calls: int = 0
        self._token_logs: List[Dict[str, int]] = []
        # Buffer for per-step AI-rejected matches to be considered at pipeline end
        self._rejected_buffer: List[MatchResult] = []
        # Capture algorithm-specific error records for Excel output
        self._error_records: List[Dict[str, Any]] = []
        
        # AI verification prompt template (aligned with ai_enhanced_reconciliation.py)
        self.match_verification_prompt = """
        You are a financial reconciliation expert. Analyze if these transactions represent the same financial event.
        
        MATCHING PARAMETERS:
        - Amount Tolerance: {amount_tolerance:.1%} (allowed difference between amounts)
        - Maximum Date Difference: {max_date_diff} days
        - Minimum Confidence Threshold: {min_confidence:.2f}
        - Semantic Similarity Threshold: {semantic_threshold:.2f}
        
        BANK TRANSACTION:
        {bank_txn}
        
        COMPANY TRANSACTION:
        {company_txn}
        
        ANALYSIS INSTRUCTIONS:
        1. Amount Matching (Weight: 40%):
           - Check if amounts match EXACTLY when amount_tolerance is 0
           - For multiple company transactions, SUM their amounts before comparing to the bank amount
           - Consider bank fees or processing charges
           - If amounts differ by ANY amount when tolerance is 0, confidence MUST be reduced significantly and CANNOT be 1.0
           - When amount_tolerance is 0, even a 0.01 difference means amounts do not match
        
        2. Date Matching (Weight: 20%):
           - Verify dates are within {max_date_diff} days of each other
           - For multiple company transactions, use the earliest and latest dates to check range
           - Consider business days and processing times
        
        3. Description Similarity (Weight: 30%):
           - Compare transaction descriptions/parties
           - Look for semantic similarities above {semantic_threshold:.2f} confidence
           - For multiple company transactions, check if bank description relates to any of them
        
        4. Reference Matching (Weight: 10%):
           - Check for matching reference/ID numbers
           - Consider partial matches with high confidence
           - For multiple company transactions, check if bank reference matches any company reference
        
        IMPORTANT EXCLUSIONS:
        - IGNORE any UID, ID, or unique identifier fields when evaluating matches
        - UIDs are purely for record identification and should NOT affect your confidence score
        - Focus on financial attributes (amount, date, description, reference) only

        GROUP/INSTALLMENT/PARTIAL HANDLING:
        - If descriptions indicate a partial, bulk, split, batch, or installment payment (e.g., contains words like PART, PARTIAL, BULK, BATCH, SPLIT, INSTALMENT/INSTALLMENT, REFUND PART X), treat this as evidence of a grouped transaction rather than a standalone 1:1 match.
        - Only accept as a 1:1 match if BOTH sides clearly refer to the SAME part (e.g., "PART 2" vs "PART 2") and other criteria are strong.
        - DO NOT consider a shared numeric suffix in references (e.g., 1009) alone as a strong reference match — require overall reference consistency (exact or clear structured match), not just suffix overlap.
        - When amount tolerance is 0, ANY non-zero difference should reduce confidence such that a 1:1 is not accepted. For groups this implies amount sums must equal exactly.

        CURRENCY FORMATTING:
        - ALWAYS use Malaysian Ringgit (RM) or MYR when referring to currency amounts
        - NEVER use $ symbol for amounts
        
        CONFIDENCE SCORING:
        - 0.9-0.99: Excellent match (all criteria strongly met)
        - 0.7-0.89: Good match (minor discrepancies)
        - 0.5-0.69: Possible match (needs review)
        - <0.5: Unlikely match (significant discrepancies)
        - CRITICAL: If amount_tolerance is 0, ANY difference in amounts MUST result in confidence < 0.9
        - CRITICAL: NEVER assign 1.0 confidence when there is ANY difference in amounts when tolerance is 0
        
        YOUR TASK:
        - Return ONLY a valid JSON object with this exact structure:
        {{ 
            "is_valid": true|false,
            "confidence": 0.0-1.0,
            "reason": "Detailed explanation of your decision"
        }}
        
        IMPORTANT:
        - DO NOT include any markdown formatting (no ```json or ```)
        - DO NOT include any text outside the JSON object
        - is_valid must be either true or false (boolean)
        - confidence must be a number between 0.0 and 1.0
        - reason must be a string
        - ALWAYS use RM or MYR for currency, NEVER use $ symbol
        """

    def _initialize_ai_circuit_breaker(self):
        """Initialize circuit breaker state and counters for AI API calls."""
        if not hasattr(self, '_ai_failure_count'):
            self._ai_failure_count = 0
        if not hasattr(self, '_ai_circuit_breaker_open'):
            self._ai_circuit_breaker_open = False
        if not hasattr(self, '_ai_call_count'):
            self._ai_call_count = 0
        if not hasattr(self, '_ai_similarity_cache'):
            self._ai_similarity_cache = {}
        if not hasattr(self, '_last_api_error'):
            self._last_api_error = None

    def _generate_cache_key(self, bank_desc: str, company_desc: str, bank_ref: str, company_ref: str) -> str:
        """Generate cache key for similar transaction matching."""
        bank_norm = (bank_desc or '').lower().strip()
        company_norm = (company_desc or '').lower().strip()
        bank_ref_norm = (bank_ref or '').lower().strip()
        company_ref_norm = (company_ref or '').lower().strip()
        return f"{bank_norm}|{company_norm}|{bank_ref_norm}|{company_ref_norm}"

    def _is_similar_transaction(self, cache_key: str) -> bool:
        """Check if a similar transaction exists in cache."""
        if not hasattr(self, '_ai_similarity_cache'):
            return False
        threshold = getattr(self.config, 'AI_CACHE_SIMILAR_THRESHOLD', 0.95)
        for existing_key in self._ai_similarity_cache.keys():
            similarity = SequenceMatcher(None, cache_key, existing_key).ratio()
            if similarity >= threshold:
                return True
        return False

    def _handle_ai_failure(
        self,
        error: Exception,
        bank_amount: float,
        company_amount: float,
        bank_date,
        company_date,
        bank_desc: str,
        company_desc: str,
        bank_ref: str,
        company_ref: str,
    ) -> Tuple[float, Dict[str, Any]]:
        """Handle AI API failures with detailed error reporting and circuit breaker logic."""
        if not hasattr(self, '_ai_failure_count'):
            self._ai_failure_count = 0

        self._ai_failure_count += 1
        self._last_api_error = str(error)

        # Detailed error categorization
        error_type = "Unknown"
        error_details = str(error)

        if "timeout" in error_details.lower():
            error_type = "API Timeout"
        elif "connection" in error_details.lower():
            error_type = "Connection Error"
        elif "401" in error_details or "unauthorized" in error_details.lower():
            error_type = "Authentication Failed"
        elif "429" in error_details or "rate limit" in error_details.lower():
            error_type = "Rate Limit Exceeded"
        elif "500" in error_details or "502" in error_details or "503" in error_details:
            error_type = "Server Error"
        elif "404" in error_details:
            error_type = "API Endpoint Not Found"

        # Check if we should open circuit breaker
        failure_threshold = getattr(self.config, 'AI_CIRCUIT_BREAKER_FAILURES', 3)
        if self._ai_failure_count >= failure_threshold:
            self._ai_circuit_breaker_open = True
            self.logger.error(
                f"AI Circuit Breaker OPENED after {self._ai_failure_count} failures. Last error: {error_type} - {error_details}"
            )
        else:
            self.logger.warning(
                f"AI API failure #{self._ai_failure_count}/{failure_threshold}: {error_type} - {error_details}"
            )

        # Return fallback verification with detailed error info
        fallback_result = self._fallback_verification(
            bank_amount,
            company_amount,
            bank_date,
            company_date,
            bank_desc,
            company_desc,
            bank_ref,
            company_ref,
        )

        # Add error details to explanation
        score, detail = fallback_result
        detail['ai_error_type'] = error_type
        detail['ai_error_details'] = error_details
        detail['ai_failure_count'] = self._ai_failure_count
        detail['circuit_breaker_open'] = getattr(self, '_ai_circuit_breaker_open', False)
        detail['explanation'] = (
            f"AI failed ({error_type}): {detail.get('explanation', '')} [Failure #{self._ai_failure_count}]"
        )

        return score, detail

    def _fallback_verification(
        self,
        bank_amount: float,
        company_amount: float,
        bank_date,
        company_date,
        bank_desc: str,
        company_desc: str,
        bank_ref: str,
        company_ref: str,
    ) -> Tuple[float, Dict[str, Any]]:
        """Fallback rule-based verification when AI is unavailable."""
        amount_tolerance = getattr(self.config, 'AMOUNT_TOLERANCE', 0.0)
        max_date_diff = getattr(self.config, 'AI_MAX_DATE_DIFF', 100)
        min_confidence = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)

        # Calculate component scores
        amt_diff = abs(bank_amount - company_amount)
        amt_comp = 1.0 - min(1.0, amt_diff / (abs(bank_amount) + 1e-6))
        # Strict: if zero tolerance, any non-zero difference must contribute 0 to amount component
        if amount_tolerance == 0.0 and amt_diff > 0:
            amt_comp = 0.0

        date_comp = float(getattr(self.config, 'DEFAULT_DATE_COMPONENT', 0.5))
        if (
            bank_date is not None
            and company_date is not None
            and not (pd.isna(bank_date) or pd.isna(company_date))
        ):
            dd = abs((bank_date - company_date).days)
            date_comp = 1.0 - min(1.0, dd / float(max_date_diff))

        desc_sim = SequenceMatcher(
            None, (bank_desc or '').lower(), (company_desc or '').lower()
        ).ratio()
        ref_sim = SequenceMatcher(
            None, (bank_ref or '').lower(), (company_ref or '').lower()
        ).ratio()

        # Weighted scoring (use configured AI weights)
        w_amt = float(getattr(self.config, 'AI_AMOUNT_WEIGHT', 0.2))
        w_date = float(getattr(self.config, 'AI_DATE_WEIGHT', 0.2))
        w_ref = float(getattr(self.config, 'AI_REF_WEIGHT', 0.2))
        w_desc = float(getattr(self.config, 'AI_DESC_WEIGHT', 0.4))
        score = w_amt * amt_comp + w_date * date_comp + w_ref * ref_sim + w_desc * desc_sim

        # Build comprehensive explanation: breakdown and why not higher/lower
        reasons = []
        positives = []
        if amount_tolerance == 0.0 and amt_diff > 0:
            reasons.append(f"amount mismatch RM {amt_diff:.2f} under zero-tolerance")
        elif amt_diff > (amount_tolerance or 0.0):
            reasons.append(f"amount differs by RM {amt_diff:.2f} (> tol {amount_tolerance:.2f})")
        else:
            positives.append("amount within tolerance")
        if bank_date is None or company_date is None or pd.isna(bank_date) or pd.isna(company_date):
            reasons.append("missing date on one side")
        else:
            reasons.append(f"date gap {dd if 'dd' in locals() else 0} days vs max {max_date_diff}")
            if 'dd' in locals() and isinstance(dd, (int, float)) and dd <= max_date_diff:
                positives.append("date within tolerance")
        if desc_sim < 0.8:
            reasons.append(f"low description similarity {desc_sim:.2f}")
        else:
            positives.append("strong description similarity")
        if ref_sim < 0.8:
            reasons.append(f"low reference similarity {ref_sim:.2f}")
        else:
            positives.append("strong reference similarity")
        why_clause = "; ".join(reasons) if reasons else "balanced components"
        why_not_lower = "; ".join(positives) if positives else "some evidence present but mixed"

        explanation = (
            f"Rule-based fallback verification (AI unavailable). "
            f"Confidence={score:.3f} (threshold {min_confidence:.2f}). "
            f"Breakdown: amount={amt_comp:.3f} (Î” RM {amt_diff:.2f}), "
            f"date={date_comp:.3f}"
            + (f" (Î” {dd} days â‰¤ {max_date_diff})" if ('dd' in locals() and bank_date is not None and company_date is not None and not (pd.isna(bank_date) or pd.isna(company_date))) else " (date missing)")
            + f", desc={desc_sim:.3f}, ref={ref_sim:.3f}. "
            f"Why not higher: {why_clause}. Why not lower: {why_not_lower}."
        )

        detail = {
            'explanation': explanation,
            'amount_component': amt_comp,
            'date_component': date_comp,
            'ref_component': ref_sim,
            'desc_component': desc_sim,
            'overall_semantic_score': (desc_sim + ref_sim) / 2,
            'ai_verification': False,
            'is_valid': score >= min_confidence,
        }
        return score, detail

    # ----- AI verification helpers (scoring + semantic) -----
    def _verify_match_with_ai(
        self,
        bank_amount: float,
        company_amount: float,
        bank_date: Optional[pd.Timestamp],
        company_date: Optional[pd.Timestamp],
        bank_desc: str,
        company_desc: str,
        bank_ref: str,
        company_ref: str,
    ) -> Tuple[float, Dict[str, Any]]:
        """AI verification using prompt-based approach aligned with ai_enhanced_reconciliation.py"""
        
        # Format transaction data for AI prompt
        bank_txn = {
            'amount': f"RM {bank_amount:.2f}",
            'date': bank_date.strftime('%Y-%m-%d') if bank_date and not pd.isna(bank_date) else 'N/A',
            'description': bank_desc or 'N/A',
            'reference': bank_ref or 'N/A'
        }
        
        company_txn = {
            'amount': f"RM {company_amount:.2f}",
            'date': company_date.strftime('%Y-%m-%d') if company_date and not pd.isna(company_date) else 'N/A',
            'description': company_desc or 'N/A',
            'reference': company_ref or 'N/A'
        }
        
        # Get configuration parameters
        amount_tolerance = getattr(self.config, 'AMOUNT_TOLERANCE', 0.0)
        max_date_diff = getattr(self.config, 'AI_MAX_DATE_DIFF', 100)
        min_confidence = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)
        semantic_threshold = float(getattr(self.config, 'AI_SEMANTIC_THRESHOLD', 0.70))
        debug_skips = bool(getattr(self.config, 'AI_DEBUG_LOG_SKIPS', True))
        force_remote = bool(getattr(self.config, 'AI_FORCE_REMOTE_VERIFY', False))
        
        # Format the AI prompt
        prompt = self.match_verification_prompt.format(
            amount_tolerance=amount_tolerance,
            max_date_diff=max_date_diff,
            min_confidence=min_confidence,
            semantic_threshold=semantic_threshold,
            bank_txn=json.dumps(bank_txn, indent=2),
            company_txn=json.dumps(company_txn, indent=2)
        )
        
        # Initialize circuit breaker and counters
        self._initialize_ai_circuit_breaker()
        
        # Check circuit breaker
        if self._ai_circuit_breaker_open:
            self.logger.info("AI Circuit Breaker is OPEN - using fallback verification")
            return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
        
        # Check API call limit
        if self._ai_call_count >= getattr(self.config, 'AI_MAX_API_CALLS', 200):
            self.logger.warning(f"AI API call limit reached ({self._ai_call_count}/{self.config.AI_MAX_API_CALLS}). Using fallback verification.")
            return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
        
        # Calculate traditional scores for confidence-based skipping
        amt_diff = abs(bank_amount - company_amount)
        amt_comp = 1.0 - min(1.0, amt_diff / (abs(bank_amount) + 1e-6))
        # Strict: if zero tolerance, any non-zero difference must contribute 0 to amount component
        if amount_tolerance == 0.0 and amt_diff > 0:
            amt_comp = 0.0
        
        date_comp = 0.5
        if bank_date is not None and company_date is not None and not (pd.isna(bank_date) or pd.isna(company_date)):
            dd = abs((bank_date - company_date).days)
            date_comp = 1.0 - min(1.0, dd / float(max_date_diff))
        
        traditional_score = (amt_comp + date_comp) / 2

        # Debug diagnostics of computed values and thresholds
        if debug_skips:
            self.logger.debug(
                "AI verify diagnostics | amt_diff=%.2f amt_comp=%.3f date_comp=%.3f trad=%.3f | thr_high=%.2f thr_low=%.2f | force_remote=%s | call_count=%d/%d | cb_open=%s",
                amt_diff,
                amt_comp,
                date_comp,
                traditional_score,
                float(getattr(self.config, 'AI_SKIP_HIGH_CONFIDENCE_THRESHOLD', 0.75)),
                float(getattr(self.config, 'AI_SKIP_LOW_CONFIDENCE_THRESHOLD', 0.50)),
                str(force_remote),
                int(self._ai_call_count),
                int(getattr(self.config, 'AI_MAX_API_CALLS', 200)),
                str(bool(getattr(self, '_ai_circuit_breaker_open', False)))
            )
        
        # Skip AI for high/low confidence matches
        if not force_remote:
            if traditional_score >= getattr(self.config, 'AI_SKIP_HIGH_CONFIDENCE_THRESHOLD', 0.75):
                if debug_skips:
                    self.logger.debug(f"[SKIP] High-confidence traditional score (%.2f) >= threshold", traditional_score)
                return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
            elif traditional_score <= getattr(self.config, 'AI_SKIP_LOW_CONFIDENCE_THRESHOLD', 0.50):
                if debug_skips:
                    self.logger.debug(f"[SKIP] Low-confidence traditional score (%.2f) <= threshold", traditional_score)
                return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
        
        # Check cache for similar transactions
        cache_key = self._generate_cache_key(bank_desc, company_desc, bank_ref, company_ref)
        if not force_remote and cache_key in self._ai_similarity_cache:
            cached_result = self._ai_similarity_cache[cache_key]
            if debug_skips:
                self.logger.debug("[SKIP] Using cached AI result for identical transaction")
            return cached_result['score'], cached_result['detail']
        
        # Check for similar transactions in cache
        if not force_remote and getattr(self.config, 'AI_ENABLE_SMART_BATCHING', True) and self._is_similar_transaction(cache_key):
            if debug_skips:
                self.logger.debug("[SKIP] Using fallback for similar cached transaction (smart batching)")
            return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
        
        # Proceed with AI verification
        api_key = getattr(self.config, 'OPEN_ROUTER_KEY', None)
        if not api_key:
            api_key = os.getenv('OPEN_ROUTER_KEY')
        
        if not api_key:
            if debug_skips:
                self.logger.warning("[SKIP] No OpenRouter API key found in config or env; using fallback verification")
            return self._fallback_verification(bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)
        
        self._ai_call_count += 1
        if debug_skips:
            models = list(getattr(self.config, 'OPENROUTER_MODELS', []) or [])
            self.logger.debug(
                "AI verification call #%d/%d (models=%s, failure_count=%d, cb_open=%s) - API key prefix=%s",
                self._ai_call_count,
                int(getattr(self.config, 'AI_MAX_API_CALLS', 200)),
                ",".join(models) if models else "<none>",
                int(getattr(self, '_ai_failure_count', 0)),
                str(bool(getattr(self, '_ai_circuit_breaker_open', False))),
                str(api_key[:10]) + "..."
            )
        
        try:
            ai_result = self._call_openrouter_api(prompt, api_key)
            if ai_result:
                desc_sim = SequenceMatcher(None, (bank_desc or '').lower(), (company_desc or '').lower()).ratio()
                ref_sim = SequenceMatcher(None, (bank_ref or '').lower(), (company_ref or '').lower()).ratio()
                
                # Build comprehensive AI explanation with components and reasons
                ai_conf = float(ai_result.get('confidence', 0.0))
                reasons = []
                positives = []
                if amount_tolerance == 0.0 and amt_diff > 0:
                    reasons.append(f"amount mismatch RM {amt_diff:.2f} under zero-tolerance")
                elif amt_diff > (amount_tolerance or 0.0):
                    reasons.append(f"amount differs by RM {amt_diff:.2f} (> tol {amount_tolerance:.2f})")
                else:
                    positives.append("amount within tolerance")
                if bank_date is None or company_date is None or pd.isna(bank_date) or pd.isna(company_date):
                    reasons.append("missing date on one side")
                else:
                    reasons.append(f"date gap {dd if 'dd' in locals() else 0} days vs max {max_date_diff}")
                    if 'dd' in locals() and isinstance(dd, (int, float)) and dd <= max_date_diff:
                        positives.append("date within tolerance")
                if desc_sim < 0.8:
                    reasons.append(f"low description similarity {desc_sim:.2f}")
                else:
                    positives.append("strong description similarity")
                if ref_sim < 0.8:
                    reasons.append(f"low reference similarity {ref_sim:.2f}")
                else:
                    positives.append("strong reference similarity")
                why_clause = "; ".join(reasons) if reasons else "balanced components"
                why_not_lower = "; ".join(positives) if positives else "some evidence present but mixed"

                explanation = (
                    f"AI verification (call #{self._ai_call_count}): {ai_result['reason']}. "
                    f"Confidence={ai_conf:.3f} (threshold {min_confidence:.2f}, semantic_thr {semantic_threshold:.2f}). "
                    f"Breakdown: amount={amt_comp:.3f} (Î” RM {amt_diff:.2f}), "
                    f"date={date_comp:.3f}"
                    + (f" (Î” {dd} days â‰¤ {max_date_diff})" if ('dd' in locals() and bank_date is not None and company_date is not None and not (pd.isna(bank_date) or pd.isna(company_date))) else " (date missing)")
                    + f", desc={desc_sim:.3f}, ref={ref_sim:.3f}. "
                    f"Why not higher: {why_clause}. Why not lower: {why_not_lower}."
                )

                detail = {
                    'amount_component': amt_comp,
                    'date_component': date_comp,
                    'ref_component': ref_sim,
                    'desc_component': desc_sim,
                    'overall_semantic_score': ai_conf,
                    'explanation': explanation,
                    'ai_verification': True,
                    'is_valid': ai_result['is_valid'],
                    'api_call_count': self._ai_call_count
                }
                # Enforce strict amount rule when configured and tolerance is zero
                try:
                    if bool(getattr(self.config, 'AI_STRICT_AMOUNT_WHEN_ZERO_TOLERANCE', True)) and amount_tolerance == 0.0 and amt_diff > 0:
                        detail['is_valid'] = False
                        # ensure confidence reflects rejection
                        ai_conf = float(ai_result.get('confidence', 0.0))
                        cap = float(getattr(self.config, 'AI_STRICT_REJECT_CONFIDENCE_CAP', 0.49))
                        detail['overall_semantic_score'] = min(ai_conf, cap)
                        detail['explanation'] += " | Rejected due to strict zero-tolerance amount mismatch"
                except Exception:
                    pass
                
                # Cache successful result
                self._ai_similarity_cache[cache_key] = {'score': ai_result['confidence'], 'detail': detail}
                
                # Reset failure count on success
                self._ai_failure_count = 0
                
                return ai_result['confidence'], detail
            else:
                raise Exception("AI API returned empty result")
                
        except Exception as e:
            return self._handle_ai_failure(e, bank_amount, company_amount, bank_date, company_date, bank_desc, company_desc, bank_ref, company_ref)

    def _get_enhanced_semantic_similarity(self, bank_desc: str, company_desc: str, bank_ref: str, company_ref: str) -> Dict[str, Any]:
        if not hasattr(self, '_semantic_cache') or self._semantic_cache is None:
            self._semantic_cache = {}
        key = f"{bank_desc}\u241f{company_desc}\u241f{bank_ref}\u241f{company_ref}"
        if key in self._semantic_cache:
            cached = self._semantic_cache.get(key) or {}
            cached.setdefault('description_score', float)
            cached.setdefault('reference_score', float)
            cached.setdefault('explanation', '')
            cached.setdefault('semantic_analysis', '')
            cached.setdefault('overall_semantic_score', float(cached.get('description_score') or 0) * 0.67 + float(cached.get('reference_score') or 0) * 0.33)
            return cached

        def simple():
            d = SequenceMatcher(None, (bank_desc or '').lower(), (company_desc or '').lower()).ratio()
            r = SequenceMatcher(None, (bank_ref or '').lower(), (company_ref or '').lower()).ratio()
            overall = 0.7 * d + 0.3 * r
            return {
                'description_score': float(d),
                'reference_score': float(r),
                'explanation': 'Fallback semantic using text similarity',
                'semantic_analysis': 'N/A',
                'overall_semantic_score': float(overall),
            }

        api_key = self.config.OPEN_ROUTER_KEY
        if not api_key:
            result = simple()
            self._remember_semantic(key, result)
            return result

        prompt = (
            "Rate the semantic similarity (0-1) between these two transaction descriptions and references.\n"
            f"Bank description: {bank_desc}\nCompany description: {company_desc}\n"
            f"Bank reference: {bank_ref}\nCompany reference: {company_ref}\n"
            "Return ONLY valid JSON: {\"description_score\": <0-1>, \"reference_score\": <0-1>, \"explanation\": \"...\"}"
        )
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

        models = list(getattr(self.config, 'OPENROUTER_MODELS', []) or [])
        if not models:
            self.logger.debug("No OPENROUTER_MODELS configured; skipping remote AI call.")
            return None

        last_error = None
        for model in models:
            try:
                data = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": int(self.config.MAX_TOKENS or 512),
                    "temperature": 0.0,
                }
                resp = requests.post(self.config.OPENROUTER_API_URL, headers=headers, json=data, timeout=60)
                if resp.status_code == 429:
                    retry_after = int(resp.headers.get('retry-after', '2'))
                    time.sleep(max(retry_after, int(getattr(self.config, 'RATE_LIMIT_DELAY', 2.0))))
                    last_error = Exception(f"Rate limited on model {model}")
                    continue
                resp.raise_for_status()
                j = resp.json()
                content = (((j or {}).get('choices') or [{}])[0].get('message') or {}).get('content') or ''
                parsed = self._safe_parse_json(content)
                if not isinstance(parsed, dict):
                    parsed = {}
                d = float(parsed.get('description_score') or 0.0)
                r = float(parsed.get('reference_score') or 0.0)
                overall = 0.7 * d + 0.3 * r
                result = {
                    'description_score': d,
                    'reference_score': r,
                    'explanation': str(parsed.get('reason') or parsed.get('explanation') or ''),
                    'semantic_analysis': str(content),
                    'overall_semantic_score': float(overall),
                }
                self._remember_semantic(key, result)
                return result
            except Exception as e:
                last_error = e
                time.sleep(0.5)

        self.logger.debug(f"Semantic API failed across models, using fallback: {last_error}")
        result = simple()
        self._remember_semantic(key, result)
        return result

    def _safe_parse_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            m = re.search(r"\{[\s\S]*\}", text)
            if m:
                try:
                    return json.loads(m.group(0))
                except Exception:
                    return {}
            return {}

    def _remember_semantic(self, key: str, value: Dict[str, Any]) -> None:
        if not hasattr(self, '_semantic_cache') or self._semantic_cache is None:
            self._semantic_cache = {}
        if len(self._semantic_cache) >= int(self.config.SEMANTIC_CACHE_SIZE or 500):
            try:
                first_key = next(iter(self._semantic_cache.keys()))
                self._semantic_cache.pop(first_key, None)
            except Exception:
                self._semantic_cache.clear()
        self._semantic_cache[key] = value

    # ----- Console summaries helpers -----
    def _extract_amount_from_row(self, row: pd.Series, is_bank: bool) -> float:
        try:
            if row is None or (isinstance(row, dict) and not row):
                return 0.0
            if isinstance(row, pd.Series):
                data = row
            elif isinstance(row, dict):
                data = row
            else:
                return 0.0
            # Prefer explicit net_amount if present
            val = data.get('net_amount') if isinstance(data, dict) else data.get('net_amount') if hasattr(data, 'get') else None
            if val is not None:
                try:
                    return abs(float(val) or 0.0)
                except Exception:
                    pass
            # Otherwise use receipt/disbursement fields
            if is_bank:
                r_field = self.config.BANK_RECEIPT_FIELD
                d_field = self.config.BANK_DISBURSEMENT_FIELD
            else:
                r_field = self.config.COMPANY_RECEIPT_FIELD
                d_field = self.config.COMPANY_DISBURSEMENT_FIELD
            r_val = 0.0
            d_val = 0.0
            try:
                r_raw = data.get(r_field) if isinstance(data, dict) else data.get(r_field)
                r_val = abs(float(r_raw or 0.0))
            except Exception:
                r_val = 0.0
            try:
                d_raw = data.get(d_field) if isinstance(data, dict) else data.get(d_field)
                d_val = abs(float(d_raw or 0.0))
            except Exception:
                d_val = 0.0
            # Pick the non-zero component; if both non-zero, choose the larger
            return max(r_val, d_val)
        except Exception:
            return 0.0

    def _estimate_match_amount(self, r: 'MatchResult') -> float:
        """Heuristic estimate of the matched amount for a MatchResult.
        Uses bank/company data dicts if present; otherwise looks up rows by ID(s).
        """
        bank_total = 0.0
        comp_total = 0.0
        try:
            # Bank side
            if isinstance(r.bank_tx_id, (list, tuple)):
                if r.bank_data:
                    # When grouped, bank_data may represent only one row; sum via df for accuracy
                    for bid in r.bank_tx_id:
                        if bid in self.bank_df.index:
                            bank_total += self._extract_amount_from_row(self.bank_df.loc[bid], is_bank=True)
                else:
                    for bid in r.bank_tx_id:
                        if bid in self.bank_df.index:
                            bank_total += self._extract_amount_from_row(self.bank_df.loc[bid], is_bank=True)
            else:
                if r.bank_data:
                    bank_total = self._extract_amount_from_row(r.bank_data, is_bank=True)
                elif r.bank_tx_id in self.bank_df.index:
                    bank_total = self._extract_amount_from_row(self.bank_df.loc[r.bank_tx_id], is_bank=True)

            # Company side
            if isinstance(r.company_tx_id, (list, tuple)):
                if isinstance(r.company_data, (list, tuple)) and r.company_data:
                    # Sum provided dicts if present
                    for cd in r.company_data:
                        comp_total += self._extract_amount_from_row(cd, is_bank=False)
                else:
                    for cid in r.company_tx_id:
                        if cid in self.company_df.index:
                            comp_total += self._extract_amount_from_row(self.company_df.loc[cid], is_bank=False)
            else:
                if isinstance(r.company_data, dict) and r.company_data:
                    comp_total = self._extract_amount_from_row(r.company_data, is_bank=False)
                elif r.company_tx_id in self.company_df.index:
                    comp_total = self._extract_amount_from_row(self.company_df.loc[r.company_tx_id], is_bank=False)
        except Exception:
            pass
        # Estimated matched is intersection; if one side missing, use the available
        if bank_total > 0 and comp_total > 0:
            return min(bank_total, comp_total)
        return bank_total if bank_total > 0 else comp_total

    def _print_step_summary(self, step_name: str, new_matches: List['MatchResult']) -> None:
        try:
            amt = sum(self._estimate_match_amount(r) for r in new_matches)
            # Avoid tiny float noise and tqdm overwriting artifacts in display
            try:
                min_disp = float(getattr(self.config, 'MIN_NONZERO_AMOUNT', 0.01))
            except Exception:
                min_disp = 0.01
            display_amt = 0.0 if abs(amt) < min_disp else amt
            # Use tqdm.write to avoid overwriting by active progress bars
            try:
                from tqdm import tqdm
                tqdm.write(f"{step_name}: {len(new_matches)} matches | Matched amount: RM {display_amt:,.2f}")
            except Exception:
                print(f"{step_name}: {len(new_matches)} matches | Matched amount: RM {display_amt:,.2f}")
        except Exception:
            print(f"{step_name}: {len(new_matches)} matches")

    # ------------- IO -------------
    def load_data(self, bank_json_path: str, company_json_path: str) -> None:
        with open(bank_json_path, 'r', encoding='utf-8-sig') as f:
            bank_data = json.load(f)
        with open(company_json_path, 'r', encoding='utf-8-sig') as f:
            company_data = json.load(f)
        self.load_data_from_dicts(bank_data, company_data)

    def load_data_from_dicts(self, bank_data: List[Dict[str, Any]], company_data: List[Dict[str, Any]]):
        # Create a temporary base reconciler to leverage its preprocessing (no inheritance)
        base_cfg = self._make_base_config()
        base = EnhancedReconciler(config=base_cfg)
        base.load_data_from_dicts(bank_data, company_data)
        # Keep references to processed dataframes
        self.bank_df = base.bank_df.copy()
        self.company_df = base.company_df.copy()
        # Track original UID universe
        self.bank_uids = set(self.bank_df.index)
        self.company_uids = set(self.company_df.index)
        # Initialize matched sets in our orchestrator
        self._matched_bank_ids = set()
        self._matched_company_ids = set()

    # ------------- Config mapping helpers -------------
    def _make_base_config(self) -> EnhancedReconciliationConfig:
        # Build a concrete EnhancedReconciliationConfig and copy over shared fields
        base_cfg = EnhancedReconciliationConfig()
        # Copy any uppercase attribute names present in both configs
        for attr in dir(base_cfg):
            if not attr.isupper():
                continue
            if hasattr(self.config, attr):
                try:
                    setattr(base_cfg, attr, getattr(self.config, attr))
                except Exception:
                    pass
        if hasattr(self.config, 'BANK_NAME'):
            try:
                setattr(base_cfg, 'BANK_NAME', getattr(self.config, 'BANK_NAME'))
            except Exception:
                pass
        return base_cfg

    # ------------- Pipeline -------------
    def reconcile(self) -> List[MatchResult]:
        if self.bank_df is None or self.company_df is None:
            raise RuntimeError("Data not loaded. Call load_data() or load_data_from_dicts() first.")

        # Stage 1: run the full traditional pipeline
        self.logger.info("Starting Stage 1: Traditional reconciliation pipeline...")
        self._error_records = []
        base = EnhancedReconciler(self._make_base_config())
        base._external_error_records = self._error_records
        base.bank_df = self.bank_df.copy()
        base.company_df = self.company_df.copy()
        base.matched_company_ids = set()
        base.matched_bank_ids = set()

        # Build ordered Stage 1 steps
        stage1_steps: List[Tuple[str, Callable[[], List[MatchResult]]]] = []
        # Custom matching (runs before other custom matchers; add more below)
        if getattr(self.config, 'ENABLE_CUSTOM_MATCHING', True):
            # Bank-specific: Bulk EFT grouping (with enable + any-bank override)
            try:
                if (
                    bool(getattr(self.config, 'ENABLE_BULK_EFT', True))
                    and (
                        str(getattr(self.config, 'BANK_NAME', '')).strip().upper() == 'MBB01'
                        or bool(getattr(self.config, 'BULK_EFT_ALLOW_ANY_BANK', False))
                    )
                    and hasattr(base, 'find_bulk_eft_matches')
                ):
                    stage1_steps.append(("Custom: Bulk EFT (L+yymm+EFT)", base.find_bulk_eft_matches))
            except Exception:
                pass
            if getattr(self.config, 'ENABLE_CUSTOM_STRUCTURED_GROUP', True) and hasattr(base, 'find_custom_structured_group_matches'):
                stage1_steps.append(("Custom: Structured Group", base.find_custom_structured_group_matches))
            if getattr(self.config, 'ENABLE_MBB02_CC_GROUPING', True) and hasattr(base, 'find_mbb02_creditcard_group_matches'):
                stage1_steps.append(("Custom: MBB02 Credit Card Group", base.find_mbb02_creditcard_group_matches))
            if getattr(self.config, 'ENABLE_JOMPAY_CR_GROUP', True) and hasattr(base, 'find_jompay_cr_group_matches_from_json'):
                stage1_steps.append((
                    "Custom: JomPAY CR Group",
                    lambda: base.find_jompay_cr_group_matches_from_json(getattr(self.config, 'JOMPAY_CONSOLIDATED_JSON', 'json/phase1_jompay_consolidated.json'))
                ))
            if getattr(self.config, 'ENABLE_CUSTOM_TRANSACTION_ID', True) and hasattr(base, 'find_transaction_id_matches'):
                stage1_steps.append(("Custom: Transaction ID", base.find_transaction_id_matches))
        stage1_steps.append(("Bank charges", base.find_bank_charges))
        stage1_steps.append(("Reverse CE/GL", base.find_reverse_ce_gl_matches))
        stage1_steps.append(("Name & Amount", base.find_name_and_amount_matches))
        if hasattr(base, 'find_hungarian_1to1_matches'):
            stage1_steps.append(("Hungarian 1:1", base.find_hungarian_1to1_matches))
        stage1_steps.append(("Exact", base.find_exact_matches))
        stage1_steps.append(("Amount-Date", base.find_amount_date_matches))
        # Transaction ID moved into Custom Matching (toggle-controlled)
        stage1_steps.append(("Fuzzy", base.find_fuzzy_matches))
        if getattr(self.config, 'ENABLE_GROUP_MATCHING', True):
            stage1_steps.append(("Group", base.find_group_matches))

        # Execute Stage 1 with progress bar
        stage1_results: List[MatchResult] = []
        from tqdm import tqdm  # local import in case environment differs
        verify_enabled = bool(getattr(self.config, 'ENABLE_AI', True) and getattr(self.config, 'ENABLE_AI_VERIFICATION', True))
        with tqdm(total=len(stage1_steps), desc="Stage 1: Traditional pipeline", leave=True) as pbar:
            for step_name, step_fn in stage1_steps:
                _new = step_fn()
                if verify_enabled and _new:
                    accepted, rejected = self._verify_matches_for_step(_new, step_name, base)
                else:
                    accepted, rejected = _new, []
                # Accumulate and sync matched sets
                stage1_results += accepted
                self._rejected_buffer.extend(rejected)
                self._print_step_summary(step_name, accepted)
                # Keep orchestrator matched sets aligned to base after possible reverts
                self._matched_bank_ids = set(getattr(base, 'matched_bank_ids', set()))
                self._matched_company_ids = set(getattr(base, 'matched_company_ids', set()))
                pbar.update(1)

        # Update orchestrator matched sets
        self._matched_bank_ids = set(getattr(base, 'matched_bank_ids', set()))
        self._matched_company_ids = set(getattr(base, 'matched_company_ids', set()))
        self.results.extend(stage1_results)
        self._error_records = list(getattr(base, '_error_records', []))
        print(f"DEBUG: After Stage 1, total results: {len(self.results)}")
        print(f"DEBUG: Stage 1 results breakdown: {[r.match_type for r in stage1_results]}")
        print(f"DEBUG: All results so far: {[r.match_type for r in self.results]}")
        
        # Check summary counts (composite removed)
        bank_charges_count = sum(1 for r in self.results if r.match_type == 'bank_charge')
        # print(f"DEBUG: Bank charges in results: {bank_charges_count}")

        # Stage 2 (Composite + Experimental) removed per request; proceed to Stage 3

        # Stage 3: AI-enhanced matching (find new matches using AI)
        if getattr(self.config, 'ENABLE_AI', True) and getattr(self.config, 'ENABLE_AI_MATCHING', True):
            self.logger.info("Starting Stage 3: AI-enhanced matching...")
            ai_results = self._run_ai_stage(base)
            if verify_enabled and ai_results:
                acc3, rej3 = self._verify_matches_for_step(ai_results, "AI Matching", base)
                self.results.extend(acc3)
                self._rejected_buffer.extend(rej3)
                # Sync matched sets after possible reverts
                self._matched_bank_ids = set(getattr(base, 'matched_bank_ids', set()))
                self._matched_company_ids = set(getattr(base, 'matched_company_ids', set()))
            else:
                self.results.extend(ai_results)

        # Stage 4: Skip global verification if per-step verification already ran
        if getattr(self.config, 'ENABLE_AI', True) and getattr(self.config, 'ENABLE_AI_VERIFICATION', True) and self.results and not verify_enabled:
            self.logger.info("Starting Stage 4: AI verification of all matches...")
            self._run_ai_verification_stage()

        # Finalize: add any per-step rejects that did not later get matched
        if self._rejected_buffer:
            kept = self._finalize_rejected_buffer()
            if kept:
                self.logger.info(f"Adding {len(kept)} rejected candidates to Possible Match sheet")
                self.results.extend(kept)

        # Final debug before return
        print(f"DEBUG: Final results count: {len(self.results)}")
        match_types = {}
        for r in self.results:
            match_types[r.match_type] = match_types.get(r.match_type, 0) + 1
        print(f"DEBUG: Final match type breakdown: {match_types}")
        # Print token usage averages if any AI calls were made
        if getattr(self, '_token_calls', 0) > 0:
            avg_in = self._token_in_total / self._token_calls if self._token_calls else 0
            avg_out = self._token_out_total / self._token_calls if self._token_calls else 0
            print(f"DEBUG: AI token usage â€” calls: {self._token_calls}, avg input tokens: {avg_in:.1f}, avg output tokens: {avg_out:.1f}, total in/out: {self._token_in_total}/{self._token_out_total}")

        return self.results

    # ------------- Per-step AI gating helpers -------------
    def _iter_ids(self, tx_id: Union[str, int, List[Union[str, int]]]) -> List[Union[str, int]]:
        if tx_id is None:
            return []
        if isinstance(tx_id, (list, tuple, np.ndarray)):
            return [x for x in tx_id if x is not None]
        return [tx_id]

    def _revert_rejected_from_base(self, base: 'EnhancedReconciler', match: MatchResult) -> None:
        try:
            for bid in self._iter_ids(match.bank_tx_id):
                try:
                    base.matched_bank_ids.discard(bid)
                except Exception:
                    pass
                try:
                    self._matched_bank_ids.discard(bid)
                except Exception:
                    pass
            for cid in self._iter_ids(match.company_tx_id):
                try:
                    base.matched_company_ids.discard(cid)
                except Exception:
                    pass
                try:
                    self._matched_company_ids.discard(cid)
                except Exception:
                    pass
        except Exception:
            pass

    def _verify_matches_for_step(
        self,
        matches: List[MatchResult],
        step_name: str,
        base: 'EnhancedReconciler',
    ) -> Tuple[List[MatchResult], List[MatchResult]]:
        accepted: List[MatchResult] = []
        rejected: List[MatchResult] = []

        if not matches:
            return accepted, rejected

        skip_ai_verification = {'bank_charge', 'reverse_ce_gl'}
        try:
            pbar = tqdm(matches, desc=f"AI Verify: {step_name}")
        except Exception:
            pbar = matches

        for m in pbar:
            try:
                # Auto-accept simple types or entries without company side
                if (m.match_type in skip_ai_verification) or (not m.company_data or m.company_tx_id == "N/A"):
                    m.verification_status = 'ACCEPTED'
                    m.ai_explanation = m.ai_explanation or 'Verification skipped'
                    accepted.append(m)
                    continue

                # Extract fields
                bank_amount = self._extract_amount_from_dict(m.bank_data, is_bank=True)
                company_amount = self._extract_amount_from_dict(m.company_data, is_bank=False)
                bank_date = self._extract_date_from_dict(m.bank_data, is_bank=True)
                company_date = self._extract_date_from_dict(m.company_data, is_bank=False)
                # Descriptions and references
                if isinstance(m.bank_data, list):
                    bank_desc = " | ".join([str(item.get(self.config.BANK_DESC_FIELD, '')) if isinstance(item, dict) else '' for item in m.bank_data])
                    bank_ref = " | ".join([str(item.get(self.config.BANK_REF_FIELD, '')) if isinstance(item, dict) else '' for item in m.bank_data])
                else:
                    bank_desc = str((m.bank_data or {}).get(self.config.BANK_DESC_FIELD, '') or '')
                    bank_ref = str((m.bank_data or {}).get(self.config.BANK_REF_FIELD, '') or '')
                if isinstance(m.company_data, list):
                    company_desc = " | ".join([str(item.get(self.config.COMPANY_DESC_FIELD, '')) if isinstance(item, dict) else '' for item in m.company_data])
                    company_ref = " | ".join([str(item.get(self.config.COMPANY_REF_FIELD, '')) if isinstance(item, dict) else '' for item in m.company_data])
                else:
                    company_desc = str((m.company_data or {}).get(self.config.COMPANY_DESC_FIELD, '') or '')
                    company_ref = str((m.company_data or {}).get(self.config.COMPANY_REF_FIELD, '') or '')

                # Run AI verification
                confidence, detail = self._verify_match_with_ai(
                    bank_amount=bank_amount,
                    company_amount=company_amount,
                    bank_date=bank_date,
                    company_date=company_date,
                    bank_desc=bank_desc,
                    company_desc=company_desc,
                    bank_ref=bank_ref,
                    company_ref=company_ref,
                )
                threshold = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)
                is_valid = bool(detail.get('is_valid', confidence >= threshold))

                m.ai_confidence = float(confidence)
                m.ai_explanation = detail.get('explanation', '')
                # Apply strict acceptance gates (can override to REJECT)
                strict_valid, strict_reason = self._apply_strict_verification_gates(m, confidence, detail)
                is_valid = is_valid and strict_valid
                if not strict_valid and strict_reason:
                    # Prepend strict reason to explanation
                    try:
                        m.ai_explanation = f"Strict gate: {strict_reason}. " + (m.ai_explanation or '')
                    except Exception:
                        pass
                m.verification_status = 'ACCEPTED' if is_valid else 'REJECTED'

                # Keep original IDs as-is for downstream reporting

                # Log decision to console and internal list (only rejected)
                if not is_valid:
                    try:
                        msg = f"[REJECT] {step_name}: {m.bank_tx_id} -> {m.company_tx_id} | conf={confidence:.3f} | reason={m.ai_explanation[:160]}"
                        tqdm.write(msg)
                    except Exception:
                        pass
                try:
                    self._ai_decisions.append({
                        'step': step_name,
                        'bank_tx_id': m.bank_tx_id,
                        'company_tx_id': m.company_tx_id,
                        'accepted': is_valid,
                        'confidence': float(confidence),
                        'reason': m.ai_explanation,
                        'match_type': m.match_type,
                    })
                except Exception:
                    pass

                if is_valid:
                    accepted.append(m)
                else:
                    # Return transactions to candidate pool by reverting base matched sets
                    rejected.append(m)
                    self._revert_rejected_from_base(base, m)
            except Exception as e:
                # On failure, keep the original match to avoid losing it, but log the failure
                try:
                    tqdm.write(f"[VERIFY-ERROR] {step_name}: {m.bank_tx_id}->{m.company_tx_id} | {e}")
                except Exception:
                    pass
                accepted.append(m)

        # Summary per step (only rejected count in debug)
        try:
            tqdm.write(f"{step_name}: AI verification rejected={len(rejected)}")
        except Exception:
            pass
        return accepted, rejected

    def _apply_strict_verification_gates(self, m: 'MatchResult', confidence: float, detail: Dict[str, Any]) -> Tuple[bool, str]:
        """Stricter acceptance criteria layered on top of model confidence.

        Returns (is_valid, reason_if_rejected).
        """
        try:
            if not getattr(self.config, 'ENABLE_STRICT_VERIFICATION', True):
                return True, ''

            # Skip strict gates for specific types (already skipped AI earlier, but be safe)
            if getattr(m, 'match_type', '') in {'bank_charge', 'reverse_ce_gl'}:
                return True, ''

            # Base stricter threshold
            min_conf = max(float(getattr(self.config, 'STRICT_MIN_CONFIDENCE', 0.8)), float(getattr(self.config, 'MIN_MATCH_SCORE', 0.7)))
            if confidence < min_conf:
                return False, f"confidence {confidence:.3f} below strict minimum {min_conf:.2f}"

            # Amount strictness: if tolerance 0, any amount diff must be rejected
            amt_tol = float(getattr(self.config, 'AMOUNT_TOLERANCE', 0.0) or 0.0)
            if amt_tol == 0.0:
                try:
                    if abs(float(getattr(m, 'amount_diff', 0.0) or 0.0)) > 1e-6:
                        return False, f"non-zero amount difference with zero tolerance (Δ RM {float(getattr(m, 'amount_diff', 0.0)):.2f})"
                except Exception:
                    pass

            # Date strictness
            try:
                date_diff = getattr(m, 'date_diff', None)
                if date_diff is None:
                    date_diff = 0
                if isinstance(date_diff, (pd.Series, np.ndarray)):
                    try:
                        date_diff = int(pd.to_numeric(date_diff, errors='coerce').min())
                    except Exception:
                        date_diff = 0
                strict_max_days = int(getattr(self.config, 'STRICT_DATE_MAX_DAYS', 30))
                # Allow larger date gaps only if both desc and ref are very strong
                if int(date_diff) > strict_max_days:
                    desc_c = float(detail.get('desc_component', 0.0) or 0.0)
                    ref_c = float(detail.get('ref_component', 0.0) or 0.0)
                    if not (desc_c >= 0.85 and ref_c >= 0.85):
                        return False, f"date gap {int(date_diff)} days exceeds strict max {strict_max_days} with insufficient text/ref support"
            except Exception:
                pass

            # Description/reference strictness
            desc_min = float(getattr(self.config, 'STRICT_DESC_MIN', 0.7) or 0.7)
            ref_min = float(getattr(self.config, 'STRICT_REF_MIN', 0.7) or 0.7)

            desc_c = float(detail.get('desc_component', 0.0) or 0.0)
            ref_c = float(detail.get('ref_component', 0.0) or 0.0)

            # If both references present, require minimum reference similarity
            require_ref = bool(getattr(self.config, 'STRICT_REQUIRE_REF_MATCH_WHEN_BOTH_PRESENT', True))
            try:
                bank_ref = ''
                company_ref = ''
                bd = getattr(m, 'bank_data', {})
                cd = getattr(m, 'company_data', {})
                if isinstance(bd, dict):
                    bank_ref = str(bd.get(self.config.BANK_REF_FIELD, '') or '')
                if isinstance(cd, dict):
                    company_ref = str(cd.get(self.config.COMPANY_REF_FIELD, '') or '')
                if bank_ref and company_ref and require_ref and ref_c < ref_min:
                    return False, f"reference similarity {ref_c:.2f} below strict minimum {ref_min:.2f}"
            except Exception:
                pass

            # Require at least one text signal above minimum
            if desc_c < desc_min and ref_c < ref_min:
                return False, f"textual alignment too weak (desc {desc_c:.2f}, ref {ref_c:.2f})"

            # Heuristic: descriptions indicate a group/partial/bulk transaction -> reject 1:1
            one_to_one_types = {
                'name_and_amount', 'enhanced_1to1', 'amount_date', 'exact', 'hungarian_1to1', 'transaction_id'
            }
            try:
                mt = (getattr(m, 'match_type', '') or '').lower()
                if mt in one_to_one_types:
                    bd = getattr(m, 'bank_data', {})
                    cd = getattr(m, 'company_data', {})
                    bdesc = ''
                    cdesc = ''
                    if isinstance(bd, dict):
                        bdesc = str(bd.get(self.config.BANK_DESC_FIELD, '') or '').lower()
                    if isinstance(cd, dict):
                        cdesc = str(cd.get(self.config.COMPANY_DESC_FIELD, '') or '').lower()
                    kw = ['partial', 'part ', ' part-', ' bulk', 'batch', 'split', 'installment', 'instalment', 'refund part']
                    def has_kw(s: str) -> bool:
                        return any(k in s for k in kw)
                    if (has_kw(bdesc) and has_kw(cdesc)):
                        # If both suggest a part/bulk, only accept if both clearly refer to the SAME part index
                        import re
                        pb = re.findall(r'part\s*(\d+)', bdesc)
                        pc = re.findall(r'part\s*(\d+)', cdesc)
                        same_part = bool(pb and pc and set(pb) & set(pc))
                        if not same_part:
                            return False, 'descriptions indicate partial/bulk; not a standalone 1:1 (route to group)'
            except Exception:
                pass

            # Group strictness: ensure multi-UID truly has >1 items
            if bool(getattr(self.config, 'STRICT_GROUP_REQUIRE_MULTIUID', True)) and isinstance(getattr(m, 'match_type', ''), str) and 'group' in m.match_type.lower():
                try:
                    bank_ids = getattr(m, 'bank_tx_id', None)
                    comp_ids = getattr(m, 'company_tx_id', None)
                    # If the group side is a list, require >1 unique ids
                    if isinstance(bank_ids, (list, tuple, set)) and len(set(map(str, bank_ids))) < 2 and (not isinstance(comp_ids, (list, tuple, set)) or len(set(map(str, comp_ids))) < 2):
                        # If neither side has multiple unique, it's not a real group
                        return False, "group requires >1 unique transactions on one side"
                except Exception:
                    pass

            return True, ''
        except Exception:
            # On failure, do not block acceptance purely due to gating logic
            return True, ''

    def _finalize_rejected_buffer(self) -> List[MatchResult]:
        """Only keep rejected candidates whose transactions remain unmatched at the end.

        This avoids duplicate rows where a later step found an accepted match
        reusing either the bank or company transaction.
        """
        if not self._rejected_buffer:
            return []
        accepted_bank = set(self._matched_bank_ids)
        accepted_company = set(self._matched_company_ids)
        kept: List[MatchResult] = []
        for m in self._rejected_buffer:
            b_ids = set(map(str, self._iter_ids(m.bank_tx_id)))
            c_ids = set(map(str, self._iter_ids(m.company_tx_id)))
            if b_ids & set(map(str, accepted_bank)):
                continue
            if c_ids & set(map(str, accepted_company)):
                continue
            kept.append(m)
        # Clear buffer and return kept
        self._rejected_buffer = []
        return kept

    # ------------- AI Stage -------------

    def _run_ai_stage(self, base: EnhancedReconciler) -> List[MatchResult]:
        """
        AI-enhanced matching to find new matches using AI scoring.
        This stage finds matches, verification happens in separate stage.
        """
        results: List[MatchResult] = []
        bank_df = base.bank_df.copy()
        company_df = base.company_df.copy()

        # Exclude already matched IDs
        bank_df = bank_df[~bank_df.index.isin(self._matched_bank_ids)]
        company_df = company_df[~company_df.index.isin(self._matched_company_ids)]

        try:
            if bank_df.empty or company_df.empty:
                return results

            # Helpers
            def net_amount(row: pd.Series, is_bank: bool) -> float:
                rfield = self.config.BANK_RECEIPT_FIELD if is_bank else self.config.COMPANY_RECEIPT_FIELD
                dfield = self.config.BANK_DISBURSEMENT_FIELD if is_bank else self.config.COMPANY_DISBURSEMENT_FIELD
                r = float(row.get(rfield, 0) or 0)
                d = float(row.get(dfield, 0) or 0)
                return float(r) - float(d)

            def date_of(row: pd.Series, is_bank: bool) -> Optional[pd.Timestamp]:
                f = self.config.BANK_DATE_FIELD if is_bank else self.config.COMPANY_DATE_FIELD
                val = row.get(f)
                try:
                    return pd.to_datetime(val) if pd.notna(val) else None
                except Exception:
                    return None

            def text_of(row: pd.Series, field: str) -> str:
                return str(row.get(field, '') or '')

            max_days = max(1, getattr(self.config, 'DATE_TOLERANCE_DAYS', 7))

            # Initialize AI circuit breaker and counters
            self._initialize_ai_circuit_breaker()
            
            # Check if AI is available before starting
            if self._ai_circuit_breaker_open:
                self.logger.warning("AI Circuit Breaker is OPEN - skipping AI matching stage")
                return results
            
            # Iterate each bank tx and find best company candidate
            print(f"\nðŸ§  AI Matching Progress (Max {self.config.AI_MAX_API_CALLS} calls):")
            
            # Batch AI matching: group transactions to reduce API calls
            batch_size = getattr(self.config, 'AI_MATCHING_BATCH_SIZE', 10)
            bank_list = list(bank_df.iterrows())
            
            # Track processed transactions to avoid duplicates
            processed_count = 0
            skipped_count = 0
            
            for batch_start in tqdm(range(0, len(bank_list), batch_size), desc="AI Matching (batch processing)", unit="batch"):
                # Check circuit breaker during processing
                if self._ai_circuit_breaker_open:
                    self.logger.warning("AI Circuit Breaker opened during processing - stopping AI matching")
                    break
                
                # Check API call limit
                if self._ai_call_count >= self.config.AI_MAX_API_CALLS:
                    self.logger.warning(f"AI API call limit reached ({self._ai_call_count}). Stopping AI matching.")
                    break
                
                batch_end = min(batch_start + batch_size, len(bank_list))
                batch = bank_list[batch_start:batch_end]
                
                # Process batch with AI batch matching
                batch_results = self._process_ai_matching_batch(batch, company_df, net_amount, date_of, text_of, max_days)
                results.extend(batch_results)
                
                # Update matched IDs and remove from candidate pool
                for result in batch_results:
                    self._matched_bank_ids.add(result.bank_tx_id)
                    self._matched_company_ids.add(result.company_tx_id)
                    if result.company_tx_id in company_df.index:
                        company_df = company_df.drop(index=[result.company_tx_id])
                
                # Update statistics
                processed_count += len(batch_results)
                
                # Old individual processing logic (kept as fallback)
                continue
                
                for b_id, b in batch:
                    b_amt = net_amount(b, True)
                    if abs(b_amt) < 0.01:
                        continue
                    b_date = date_of(b, True)
                    b_desc = text_of(b, self.config.BANK_DESC_FIELD)
                    b_ref = text_of(b, self.config.BANK_REF_FIELD).strip()

                    # Candidate pruning by date window if available
                    cand_df = company_df
                    if b_date is not None:
                        c_dates = pd.to_datetime(company_df[self.config.COMPANY_DATE_FIELD], errors='coerce')
                        mask = (c_dates >= b_date - pd.Timedelta(days=max_days)) & (c_dates <= b_date + pd.Timedelta(days=max_days))
                        cand_df = company_df[mask]
                        if cand_df.empty:
                            continue

                    best = None
                    best_score = -1.0
                    best_detail: Dict[str, Any] = {}

                    for c_id, c in cand_df.iterrows():
                        c_amt = net_amount(c, False)
                        c_date = date_of(c, False)
                        c_desc = text_of(c, self.config.COMPANY_DESC_FIELD)
                        c_ref = text_of(c, self.config.COMPANY_REF_FIELD).strip()

                        # Fallback to individual AI verification if batch processing is disabled
                        score, detail = self._verify_match_with_ai(
                            bank_amount=b_amt,
                            company_amount=c_amt,
                            bank_date=b_date,
                            company_date=c_date,
                            bank_desc=b_desc,
                            company_desc=c_desc,
                            bank_ref=b_ref,
                            company_ref=c_ref,
                        )
                        
                        # Track processing statistics
                        if detail.get('ai_verification', False):
                            processed_count += 1
                        else:
                            skipped_count += 1

                        if score > best_score:
                            best_score = score
                            best = (c_id, c)
                            best_detail = detail

                    # Thresholding based on MIN_MATCH_SCORE
                    min_thr = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)
                    if best is not None and best_score >= min_thr:
                        cid, crow = best
                        # Build explanation and payloads
                        exp_str = (
                            f"AI score={best_score:.3f}; "
                            f"amt={best_detail.get('amount_component', 0):.2f}, "
                            f"date={best_detail.get('date_component', 0):.2f}, "
                            f"ref={best_detail.get('ref_component', 0):.2f}, "
                            f"desc={best_detail.get('desc_component', 0):.2f}; "
                            f"semantic={best_detail.get('overall_semantic_score', 0):.2f}. "
                            f"{best_detail.get('explanation','')}"
                        )
                        results.append(MatchResult(
                            bank_tx_id=b_id,
                            company_tx_id=cid,
                            match_score=float(best_score),
                            match_type="AI-Enhanced",
                            transaction_type=(
                                'receipt' if abs(float(b.get(self.config.BANK_RECEIPT_FIELD, 0) or 0)) >= 
                                abs(float(b.get(self.config.BANK_DISBURSEMENT_FIELD, 0) or 0)) else 'disbursement'
                            ),
                            amount_diff=abs(b_amt - net_amount(crow, False)),
                            date_diff=(
                                abs((date_of(b, True) - date_of(crow, False)).days)
                                if (date_of(b, True) is not None and date_of(crow, False) is not None) else None
                            ),
                            explanation=exp_str,
                            bank_data=b.to_dict(),
                            company_data=crow.to_dict(),
                        ))
                        # Lock 1:1
                        self._matched_bank_ids.add(b_id)
                        self._matched_company_ids.add(cid)
                        # Remove matched from candidate pool quickly
                        company_df = company_df.drop(index=[cid])

            # Log comprehensive AI matching statistics
            total_transactions = len(bank_list)
            matches_found = len(results)
            api_calls_used = getattr(self, '_ai_call_count', 0)
            cache_hits = total_transactions - processed_count - skipped_count
            
            self.logger.info(f"ðŸ§  AI Matching Complete:")
            self.logger.info(f"  â€¢ Transactions processed: {total_transactions}")
            self.logger.info(f"  â€¢ Matches found: {matches_found}")
            self.logger.info(f"  â€¢ API calls used: {api_calls_used}/{self.config.AI_MAX_API_CALLS}")
            self.logger.info(f"  â€¢ AI verifications: {processed_count}")
            self.logger.info(f"  â€¢ Fallback verifications: {skipped_count}")
            self.logger.info(f"  â€¢ Cache hits: {cache_hits}")
            
            if hasattr(self, '_ai_circuit_breaker_open') and self._ai_circuit_breaker_open:
                self.logger.warning(f"  â€¢ Circuit breaker: OPEN (failures: {getattr(self, '_ai_failure_count', 0)})")
                self.logger.warning(f"  â€¢ Last error: {getattr(self, '_last_api_error', 'N/A')}")
            
            if results:
                self._print_step_summary("AI-Enhanced Matching", results)
                
        except Exception as e:
            self.logger.error(f"AI stage failed: {e}")
            # Handle circuit breaker on stage failure
            if hasattr(self, '_ai_failure_count'):
                self._ai_failure_count += 1
                failure_threshold = getattr(self.config, 'AI_CIRCUIT_BREAKER_FAILURES', 3)
                if self._ai_failure_count >= failure_threshold:
                    self._ai_circuit_breaker_open = True
                    self.logger.error(f"AI Circuit Breaker OPENED due to stage failure")
        
        return results
    
    def _process_ai_matching_batch(self, bank_batch, company_df, net_amount, date_of, text_of, max_days) -> List[MatchResult]:
        """Process a batch of bank transactions against company transactions using batch AI matching."""
        batch_results = []
        
        # Prepare batch data for AI
        batch_pairs = []
        pair_metadata = []
        
        for b_id, b in bank_batch:
            b_amt = net_amount(b, True)
            if abs(b_amt) < 0.01:
                continue
                
            b_date = date_of(b, True)
            b_desc = text_of(b, self.config.BANK_DESC_FIELD)
            b_ref = text_of(b, self.config.BANK_REF_FIELD).strip()
            
            # Candidate pruning by date window
            cand_df = company_df
            if b_date is not None:
                c_dates = pd.to_datetime(company_df[self.config.COMPANY_DATE_FIELD], errors='coerce')
                mask = (c_dates >= b_date - pd.Timedelta(days=max_days)) & (c_dates <= b_date + pd.Timedelta(days=max_days))
                cand_df = company_df[mask]
                if cand_df.empty:
                    continue
            
            # Limit candidates to top N by amount similarity for efficiency
            top_candidates = []
            for c_id, c in cand_df.iterrows():
                c_amt = net_amount(c, False)
                amt_diff = abs(b_amt - c_amt)
                amt_score = 1.0 - min(1.0, amt_diff / (abs(b_amt) + 1e-6))
                top_candidates.append((amt_score, c_id, c))
            
            # Sort by amount similarity and take top 5 candidates
            top_candidates.sort(key=lambda x: x[0], reverse=True)
            top_candidates = top_candidates[:5]
            
            # Add to batch
            for amt_score, c_id, c in top_candidates:
                c_amt = net_amount(c, False)
                c_date = date_of(c, False)
                c_desc = text_of(c, self.config.COMPANY_DESC_FIELD)
                c_ref = text_of(c, self.config.COMPANY_REF_FIELD).strip()
                
                batch_pairs.append({
                    'bank_txn': {
                        'amount': f"RM {b_amt:.2f}",
                        'date': b_date.strftime('%Y-%m-%d') if b_date and not pd.isna(b_date) else 'N/A',
                        'description': b_desc or 'N/A',
                        'reference': b_ref or 'N/A'
                    },
                    'company_txn': {
                        'amount': f"RM {c_amt:.2f}",
                        'date': c_date.strftime('%Y-%m-%d') if c_date and not pd.isna(c_date) else 'N/A',
                        'description': c_desc or 'N/A',
                        'reference': c_ref or 'N/A'
                    }
                })
                
                pair_metadata.append({
                    'bank_id': b_id, 'bank_row': b, 'bank_amt': b_amt, 'bank_date': b_date,
                    'company_id': c_id, 'company_row': c, 'company_amt': c_amt, 'company_date': c_date,
                    'amt_score': amt_score
                })
        
        if not batch_pairs:
            return batch_results
        
        # Call batch AI matching
        batch_ai_results = self._call_batch_ai_matching(batch_pairs)
        
        if batch_ai_results:
            # Process results
            min_thr = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)
            
            for i, ai_result in enumerate(batch_ai_results):
                if i >= len(pair_metadata):
                    break
                    
                metadata = pair_metadata[i]
                confidence = ai_result.get('confidence', 0.0)
                
                if confidence >= min_thr:
                    b_id = metadata['bank_id']
                    c_id = metadata['company_id']
                    b = metadata['bank_row']
                    c = metadata['company_row']
                    
                    # Check if already matched
                    if b_id in self._matched_bank_ids or c_id in self._matched_company_ids:
                        continue
                    
                    exp_str = f"Batch AI score={confidence:.3f}; {ai_result.get('reason', '')}"
                    
                    batch_results.append(MatchResult(
                        bank_tx_id=b_id,
                        company_tx_id=c_id,
                        match_score=float(confidence),
                        match_type="AI-Enhanced-Batch",
                        transaction_type=(
                            'receipt' if abs(float(b.get(self.config.BANK_RECEIPT_FIELD, 0) or 0)) >= 
                            abs(float(b.get(self.config.BANK_DISBURSEMENT_FIELD, 0) or 0)) else 'disbursement'
                        ),
                        amount_diff=abs(metadata['bank_amt'] - metadata['company_amt']),
                        date_diff=(
                            abs((metadata['bank_date'] - metadata['company_date']).days)
                            if (metadata['bank_date'] is not None and metadata['company_date'] is not None) else None
                        ),
                        explanation=exp_str,
                        bank_data=b.to_dict(),
                        company_data=c.to_dict(),
                    ))
                    # Immediately mark these IDs as matched to avoid reuse in subsequent batches
                    try:
                        self._matched_bank_ids.add(b_id)
                        self._matched_company_ids.add(c_id)
                    except Exception:
                        pass
        
        return batch_results
    
    def _call_batch_ai_matching(self, batch_pairs) -> Optional[List[Dict[str, Any]]]:
        """Call OpenRouter API for batch AI matching."""
        api_key = getattr(self.config, 'OPEN_ROUTER_KEY', None)
        if not api_key:
            api_key = os.getenv('OPEN_ROUTER_KEY')
        
        if not api_key:
            self.logger.warning("No OpenRouter API key found for batch AI matching")
            return None
        
        # Initialize circuit breaker
        self._initialize_ai_circuit_breaker()
        
        if self._ai_circuit_breaker_open:
            return None
        
        # Prepare batch prompt
        prompt = self._create_batch_matching_prompt(batch_pairs)
        
        self._ai_call_count += 1
        self.logger.debug(f"Batch AI matching call #{self._ai_call_count}/{self.config.AI_MAX_API_CALLS} - processing {len(batch_pairs)} pairs")
        
        try:
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            
            models = list(getattr(self.config, 'OPENROUTER_MODELS', []) or [])
            if not models:
                return None
            
            # Stateful rotation start index
            start_idx = int(getattr(self, '_model_rotation_index', 0)) % len(models)
            max_retries = int(getattr(self.config, 'MAX_RETRIES', 3))
            retry_delay = float(getattr(self.config, 'RATE_LIMIT_DELAY', 0.5))
            self.logger.info(f"ðŸ¤– Batch AI model rotation starting at index {start_idx} over {len(models)} models")

            # Try each model starting from rotation index
            for offset in range(len(models)):
                idx = (start_idx + offset) % len(models)
                model = models[idx]
                self.logger.info(f"ðŸ”„ Batch matching using model [{idx+1}/{len(models)}]: {model}")

                attempt = 0
                while attempt < max_retries:
                    attempt += 1
                    self.logger.debug(f"   ðŸ“¡ Attempt {attempt}/{max_retries} for model: {model}")
                    try:
                        data = {
                            "model": model,
                            "messages": [{"role": "user", "content": prompt}],
                            "max_tokens": int(getattr(self.config, 'MAX_TOKENS', 2048)),  # Increased for batch
                            "temperature": 0.0
                        }
                        resp = requests.post(
                            getattr(self.config, 'OPENROUTER_API_URL', 'https://openrouter.ai/api/v1/chat/completions'),
                            headers=headers,
                            json=data,
                            timeout=60
                        )

                        # Handle rate limit: move to next model immediately
                        if resp.status_code == 429:
                            self.logger.warning(f"âš ï¸  Rate limited (429) on {model} - switching to next model")
                            break

                        # Retry same model on 5xx
                        if 500 <= resp.status_code < 600:
                            self.logger.warning(f"ðŸ”¥ Server error {resp.status_code} on {model} (attempt {attempt}/{max_retries})")
                            if attempt < max_retries:
                                self.logger.debug(f"   â³ Waiting {retry_delay}s before retry...")
                                time.sleep(retry_delay)
                                continue
                            else:
                                self.logger.warning(f"âŒ Max retries reached for {model} - switching to next model")
                                break

                        # Other non-200: try next model
                        if resp.status_code != 200:
                            body_preview = (resp.text or '')[:400]
                            self.logger.warning(f"âŒ API error {resp.status_code} for {model}: {body_preview}...")
                            try:
                                dump_path = self._dump_llm_output('batch_api_error', model, resp.text or '')
                                if dump_path:
                                    self.logger.info(f"ðŸ“„ Saved API error body to: {dump_path}")
                            except Exception:
                                pass
                            break

                        result = resp.json()
                        content = (((result or {}).get("choices") or [{}])[0].get("message") or {}).get("content", "")

                        parsed = self._parse_batch_ai_response(content)
                        if parsed:
                            # Advance rotation index to next model for subsequent calls
                            self._model_rotation_index = (idx + 1) % len(models)
                            self.logger.info(f"âœ… Batch AI matching successful with model {model}: {len(parsed)} results | next rotation index {self._model_rotation_index}")
                            return parsed
                        else:
                            # Dump raw content for debugging
                            try:
                                dump_path = self._dump_llm_output('batch_unparseable', model, content or '')
                            except Exception:
                                dump_path = None
                            preview = (content or '')[:500]
                            self.logger.warning(
                                f"âŒ Invalid/Unparseable response from {model}; trying next model | preview: {preview}..."
                            )
                            if dump_path:
                                self.logger.info(f"ðŸ“„ Full LLM output saved to: {dump_path}")
                            break

                    except requests.exceptions.Timeout:
                        self.logger.warning(f"â° Timeout on {model} (attempt {attempt}/{max_retries})")
                        if attempt < max_retries:
                            self.logger.debug(f"   â³ Waiting {retry_delay}s before retry...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            self.logger.warning(f"âŒ Max retries reached for {model} due to timeout - switching to next model")
                            break
                    except Exception as e:
                        self.logger.warning(f"ðŸ’¥ Exception on {model} (attempt {attempt}/{max_retries}): {e}")
                        if attempt < max_retries:
                            self.logger.debug(f"   â³ Waiting {retry_delay}s before retry...")
                            time.sleep(retry_delay)
                            continue
                        else:
                            self.logger.warning(f"âŒ Max retries reached for {model} due to exception - switching to next model")
                            break

                # Advance rotation index even if this model failed, to distribute load next call
                self._model_rotation_index = (idx + 1) % len(models)
                self.logger.debug(f"   â†ªï¸  Advancing rotation index to {self._model_rotation_index}")

            self.logger.error(f"ðŸš« All {len(models)} models failed for batch AI matching - returning None")
            return None
                
        except Exception as e:
            self.logger.error(f"Batch AI matching failed: {e}")
            return None
    
    def _create_batch_matching_prompt(self, batch_pairs) -> str:
        """Create a prompt for batch AI matching."""
        prompt = """
You are a financial reconciliation expert. Analyze the following batch of bank-company transaction pairs and determine which ones represent the same financial events.

For each pair, analyze:
1. Amount Matching (40% weight): Check if amounts match within tolerance
2. Date Matching (20% weight): Verify dates are within reasonable range
3. Description Similarity (30% weight): Compare transaction descriptions semantically
4. Reference Matching (10% weight): Check for matching reference numbers

IMPORTANT:
- Use Malaysian Ringgit (RM) currency format
- Return ONLY valid JSON array with this exact structure for each pair:
- Do NOT include markdown formatting

TRANSACTION PAIRS:
"""
        
        for i, pair in enumerate(batch_pairs):
            prompt += f"\nPair {i+1}:\n"
            prompt += f"Bank: {json.dumps(pair['bank_txn'], indent=2)}\n"
            prompt += f"Company: {json.dumps(pair['company_txn'], indent=2)}\n"
        
        prompt += f"""

Return a JSON array with {len(batch_pairs)} objects, each with:
{{
    "is_valid": true|false,
    "confidence": 0.0-1.0,
    "reason": "Detailed explanation"
}}

Example: [{{"is_valid": true, "confidence": 0.85, "reason": "Amounts match exactly, dates within 2 days, descriptions similar"}}]
"""
        
        return prompt
    
    def _parse_batch_ai_response(self, content: str) -> Optional[List[Dict[str, Any]]]:
        """Parse batch AI response into structured results."""
        try:
            # Try direct JSON parsing
            parsed = json.loads(content)
            if isinstance(parsed, list):
                return parsed
        except Exception:
            pass
        
        # Try to extract JSON array from content
        import re
        json_match = re.search(r'\[\s*\{[\s\S]*\}\s*\]', content)
        if json_match:
            try:
                parsed = json.loads(json_match.group(0))
                if isinstance(parsed, list):
                    return parsed
            except Exception:
                pass
        
        # Fallback: try to parse individual objects
        try:
            objects = re.findall(r'\{[^{}]*\}', content)
            results = []
            for obj_str in objects:
                try:
                    obj = json.loads(obj_str)
                    if 'is_valid' in obj and 'confidence' in obj:
                        results.append(obj)
                except Exception:
                    continue
            return results if results else None
        except Exception:
            return None

    def _dump_llm_output(self, purpose: str, model: str, content: str) -> Optional[str]:
        """Persist raw LLM output for debugging and return the file path."""
        try:
            base_dir = getattr(self.config, 'LLM_DUMP_DIR', 'llm_dumps')
            os.makedirs(base_dir, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
            safe_model = re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(model or 'unknown'))
            file_name = f"{purpose}_{safe_model}_{ts}.txt"
            file_path = os.path.join(base_dir, file_name)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content or '')
            return file_path
        except Exception as e:
            try:
                self.logger.debug(f"Failed to write LLM dump: {e}")
            except Exception:
                pass
            return None
    
    def _run_ai_verification_stage(self) -> None:
        """Run AI verification on all matches found by previous stages."""
        if not self.results:
            self.logger.warning("No matches to verify with AI")
            return

        self.logger.info(f"Running AI verification on {len(self.results)} matches")
        verified_results: List[MatchResult] = []
        rejected_matches: List[MatchResult] = []
        self._ai_decisions = []

        # Match types that should skip AI verification (auto-accept)
        skip_ai_verification = {'bank_charge', 'reverse_ce_gl'}

        # Progress bar for AI verification
        print(f"\nðŸ¤– AI Verification Progress:")
        # Process verification in batches to reduce API calls
        batch_size = getattr(self.config, 'AI_VERIFICATION_BATCH_SIZE', 20)
        
        for batch_start in tqdm(range(0, len(self.results), batch_size), desc="AI Verifying (batched)", unit="batch"):
            batch_end = min(batch_start + batch_size, len(self.results))
            batch_matches = self.results[batch_start:batch_end]
            
            for i, match_result in enumerate(batch_matches, batch_start):
                try:
                    # Skip AI verification for certain match types that don't need it
                    if match_result.match_type in skip_ai_verification:
                        print(f"DEBUG: Skipping AI verification for {match_result.match_type} match")
                        verified_results.append(match_result)
                        continue

                    bank_data = match_result.bank_data
                    company_data = match_result.company_data

                    # Skip AI verification if company data is empty (like bank charges)
                    if not company_data or company_data == {} or match_result.company_tx_id == "N/A":
                        print(f"DEBUG: Skipping AI verification for match with no company data: {match_result.match_type}")
                        verified_results.append(match_result)
                        continue

                    # Amounts
                    bank_amount = self._extract_amount_from_dict(bank_data, is_bank=True)
                    company_amount = self._extract_amount_from_dict(company_data, is_bank=False)

                    # Dates
                    bank_date = self._extract_date_from_dict(bank_data, is_bank=True)
                    company_date = self._extract_date_from_dict(company_data, is_bank=False)

                    # Descriptions and references (handle dict or list of dicts)
                    if isinstance(bank_data, list):
                        bank_desc = " | ".join([str(item.get(self.config.BANK_DESC_FIELD, '')) if isinstance(item, dict) else '' for item in bank_data])
                        bank_ref = " | ".join([str(item.get(self.config.BANK_REF_FIELD, '')) if isinstance(item, dict) else '' for item in bank_data])
                    elif isinstance(bank_data, dict):
                        bank_desc = str(bank_data.get(self.config.BANK_DESC_FIELD, '') or '')
                        bank_ref = str(bank_data.get(self.config.BANK_REF_FIELD, '') or '')
                    else:
                        bank_desc = ''
                        bank_ref = ''

                    if isinstance(company_data, list):
                        company_desc = " | ".join([str(item.get(self.config.COMPANY_DESC_FIELD, '')) if isinstance(item, dict) else '' for item in company_data])
                        company_ref = " | ".join([str(item.get(self.config.COMPANY_REF_FIELD, '')) if isinstance(item, dict) else '' for item in company_data])
                    elif isinstance(company_data, dict):
                        company_desc = str(company_data.get(self.config.COMPANY_DESC_FIELD, '') or '')
                        company_ref = str(company_data.get(self.config.COMPANY_REF_FIELD, '') or '')
                    else:
                        company_desc = ''
                        company_ref = ''

                    # AI verification
                    confidence, detail = self._verify_match_with_ai(
                        bank_amount=bank_amount,
                        company_amount=company_amount,
                        bank_date=bank_date,
                        company_date=company_date,
                        bank_desc=bank_desc,
                        company_desc=company_desc,
                        bank_ref=bank_ref,
                        company_ref=company_ref,
                    )

                    # Use general threshold
                    threshold = getattr(self.config, 'MIN_MATCH_SCORE', 0.7)
                    is_valid = detail.get('is_valid', confidence >= threshold)

                    # Add AI verification data to the match result
                    match_result.ai_confidence = float(confidence)
                    match_result.ai_explanation = detail.get('explanation', 'AI verification completed')
                    match_result.verification_status = 'ACCEPTED' if is_valid else 'REJECTED'

                    if is_valid:
                        verified_results.append(match_result)
                    else:
                        rejected_matches.append(match_result)

                except Exception as e:
                    self.logger.error(
                        f"AI verification failed for match {match_result.bank_tx_id}->{match_result.company_tx_id}: {e}"
                    )
                    # Keep original match if verification fails
                    verified_results.append(match_result)

        # Finalize results
        original_count = len(self.results)
        # Keep both accepted and rejected matches in self.results so Excel export can include both.
        # The 'verification_status' column distinguishes ACCEPTED vs REJECTED.
        self.results = verified_results + rejected_matches
        verified_count = len(verified_results)
        rejected_count = len(rejected_matches)

        self.logger.info(
            f"AI Verification completed: {verified_count} accepted, {rejected_count} rejected out of {original_count} total matches"
        )

        if rejected_matches:
            self.logger.info(
                f"Rejected matches: {[f'{m.bank_tx_id}->{m.company_tx_id}' for m in rejected_matches[:5]]}{'...' if len(rejected_matches) > 5 else ''}"
            )
    
    def _extract_amount_from_dict(self, data: Union[Dict[str, Any], List[Dict[str, Any]]], is_bank: bool) -> float:
        """Extract amount from transaction dictionary or list of dictionaries"""
        try:
            # Handle list of transactions (group match)
            if isinstance(data, list):
                total_amount = 0.0
                for item in data:
                    if isinstance(item, dict):
                        total_amount += self._extract_amount_from_dict(item, is_bank)
                return total_amount
            
            # Handle single transaction (dictionary)
            if not isinstance(data, dict):
                return 0.0
                
            # Try net_amount first
            if 'net_amount' in data:
                return float(data['net_amount'] or 0)
            
            # Use receipt/disbursement fields
            if is_bank:
                r_field = self.config.BANK_RECEIPT_FIELD
                d_field = self.config.BANK_DISBURSEMENT_FIELD
            else:
                r_field = self.config.COMPANY_RECEIPT_FIELD
                d_field = self.config.COMPANY_DISBURSEMENT_FIELD
            
            r_val = float(data.get(r_field, 0) or 0)
            d_val = float(data.get(d_field, 0) or 0)
            return r_val - d_val
        except Exception as e:
            self.logger.debug(f"Error extracting amount: {e}")
            return 0.0
    
    def _extract_date_from_dict(self, data: Union[Dict[str, Any], List[Dict[str, Any]]], is_bank: bool) -> Optional[pd.Timestamp]:
        """Extract date from transaction dictionary or list of dictionaries"""
        try:
            # Handle list of transactions (group match)
            if isinstance(data, list):
                # For group transactions, return the earliest date
                dates = []
                for item in data:
                    if isinstance(item, dict):
                        date = self._extract_date_from_dict(item, is_bank)
                        if date is not None:
                            dates.append(date)
                return min(dates) if dates else None
            
            # Handle single transaction (dictionary)
            if not isinstance(data, dict):
                return None
                
            field = self.config.BANK_DATE_FIELD if is_bank else self.config.COMPANY_DATE_FIELD
            val = data.get(field)
            if val:
                return pd.to_datetime(val)
        except Exception as e:
            self.logger.debug(f"Error extracting date: {e}")
        return None

    # ------------- Outputs -------------
    def get_unmatched_transactions(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        if self.bank_df is None or self.company_df is None:
            raise RuntimeError("Data not loaded")
        unmatched_bank = self.bank_df[~self.bank_df.index.isin(self._matched_bank_ids)].copy()
        unmatched_company = self.company_df[~self.company_df.index.isin(self._matched_company_ids)].copy()
        return unmatched_bank, unmatched_company

    def save_results_to_excel(self, path: str) -> None:
        if not self.results and not getattr(self, '_error_records', []):
            self.logger.info("No results to save.")
            return
        
        # Prepare data for the new 3-sheet structure
        one_to_one_matches = []
        group_matches = []
        possible_matches = []
        error_rows = list(getattr(self, '_error_records', []))
        
        for r in self.results:
            # Determine if this is a group match or 1:1 match
            is_group_match = self._is_group_match(r)
            
            # Determine if this should go to Possible Match sheet
            is_possible_match = self._is_possible_match(r)
            
            if is_possible_match:
                possible_matches.append(self._format_match_row(r, is_group_match))
            elif is_group_match:
                group_matches.append(self._format_match_row(r, is_group_match))
            else:
                one_to_one_matches.append(self._format_match_row(r, is_group_match))
        
        # Create DataFrames
        df_1to1 = pd.DataFrame(one_to_one_matches) if one_to_one_matches else pd.DataFrame()
        df_group = pd.DataFrame(group_matches) if group_matches else pd.DataFrame()
        df_possible = pd.DataFrame(possible_matches) if possible_matches else pd.DataFrame()
        error_columns = self._get_column_headers() + ['Remark']
        df_error = pd.DataFrame(error_rows) if error_rows else pd.DataFrame(columns=error_columns)
        if not df_error.empty:
            df_error = df_error.reindex(columns=error_columns, fill_value='')
        
        # Write to Excel with new structure
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with pd.ExcelWriter(path, engine='xlsxwriter') as writer:
            try:
                # Write the 3 required sheets (Excel-compatible names)
                if not df_1to1.empty:
                    df_1to1.to_excel(writer, index=False, sheet_name='1to1 Matches')
                else:
                    # Create empty sheet with headers
                    empty_df = pd.DataFrame(columns=self._get_column_headers())
                    empty_df.to_excel(writer, index=False, sheet_name='1to1 Matches')
                
                if not df_group.empty:
                    df_group.to_excel(writer, index=False, sheet_name='Group Match')
                else:
                    # Create empty sheet with headers
                    empty_df = pd.DataFrame(columns=self._get_column_headers())
                    empty_df.to_excel(writer, index=False, sheet_name='Group Match')
                
                if not df_possible.empty:
                    df_possible.to_excel(writer, index=False, sheet_name='Possible Match')
                else:
                    # Create empty sheet with headers
                    empty_df = pd.DataFrame(columns=self._get_column_headers())
                    empty_df.to_excel(writer, index=False, sheet_name='Possible Match')

                if not df_error.empty:
                    df_error.to_excel(writer, index=False, sheet_name='Error')
                else:
                    empty_error_df = pd.DataFrame(columns=error_columns)
                    empty_error_df.to_excel(writer, index=False, sheet_name='Error')
                    
            except Exception as e:
                self.logger.warning(f"Could not write match sheets: {e}")
    
    def _is_group_match(self, match_result) -> bool:
        """Determine if a match result represents a group match (1:N, N:1, or N:N)"""
        bank_is_list = isinstance(match_result.bank_data, list) or isinstance(getattr(match_result, 'bank_tx_id', None), (list, tuple))
        company_is_list = isinstance(match_result.company_data, list) or isinstance(getattr(match_result, 'company_tx_id', None), (list, tuple))

        if bank_is_list or company_is_list:
            return True

        # Treat duplicate UIDs (multiple rows with same UID) as group as well
        def _has_duplicate_uid(df: pd.DataFrame, tx_id: Any) -> bool:
            try:
                uid = self._normalize_tx_id(tx_id)
                if uid is None:
                    return False
                if uid in df.index:
                    row = df.loc[uid]
                    return isinstance(row, pd.DataFrame) and len(row) > 1
                return False
            except Exception:
                return False

        if _has_duplicate_uid(self.bank_df, getattr(match_result, 'bank_tx_id', None)):
            return True
        if _has_duplicate_uid(self.company_df, getattr(match_result, 'company_tx_id', None)):
            return True

        return False
    
    def _is_possible_match(self, match_result) -> bool:
        """Determine if a match should go to Possible Match sheet"""
        # Check if rejected or low confidence
        if hasattr(match_result, 'verification_status') and match_result.verification_status == 'REJECTED':
            return True
        
        if hasattr(match_result, 'ai_confidence') and match_result.ai_confidence is not None:
            return match_result.ai_confidence < 0.7
        
        return False
    
    def _get_column_headers(self) -> list:
        """Define the column headers for the Excel output"""
        return [
            'Bank Statement Date', 'Bank Transaction ID', 'Bank Reference Number', 
            'Bank Description', 'Bank Receipt', 'Bank Disbursement',
            'CSGP Transaction Date', 'CSGP Reference', 'CSGP Module', 'CSGP Description',
            'CSGP Receipt', 'CSGP Disbursement',
            'Amount Difference', 'Date Difference', 'Reason', 
            'Confidence', 'Match Type', 'Bank_UID', 'CSGP_UID'
        ]
    
    def _safe_amount(self, value: Any) -> float:
        """Safely convert an amount-like value to a float scalar (NaN -> 0.0)."""
        try:
            num = pd.to_numeric(value, errors='coerce')
            if pd.isna(num):
                return 0.0
            # If it's a pandas scalar, convert to python float
            return float(num)
        except Exception:
            return 0.0

    def _safe_str(self, value: Any) -> str:
        """Safely stringify values, formatting Timestamps with configured DATE_FORMAT."""
        try:
            # Treat pandas/NumPy NaN/NA as empty
            if value is None or (isinstance(value, (float, int, str, pd.Timestamp, datetime, np.generic)) and pd.isna(value)):
                return ''
            # If a pandas Series or numpy array/list, join non-empty unique values
            if isinstance(value, pd.Series):
                parts = [self._safe_str(v) for v in value.tolist() if not (isinstance(v, float) and pd.isna(v))]
                # Remove empties and deduplicate while preserving order
                seen = set(); cleaned = []
                for p in parts:
                    if p and p not in seen:
                        cleaned.append(p); seen.add(p)
                return ', '.join(cleaned)
            if isinstance(value, (list, tuple, np.ndarray)):
                parts = [self._safe_str(v) for v in list(value)]
                seen = set(); cleaned = []
                for p in parts:
                    if p and p not in seen:
                        cleaned.append(p); seen.add(p)
                return ', '.join(cleaned)
            if isinstance(value, (pd.Timestamp, datetime)):
                try:
                    return value.strftime(getattr(self.config, 'DATE_FORMAT', '%Y-%m-%d'))
                except Exception:
                    return str(value)
            return '' if value is None or pd.isna(value) else str(value)
        except Exception:
            return ''

    def _normalize_tx_id(self, tx_id: Any) -> Optional[str]:
        """Normalize a transaction identifier into a string key present in the DataFrame index.

        Handles cases where tx_id may be a dict/Series containing 'UID'.
        """
        try:
            if tx_id is None:
                return None
            # If a pandas Series (row), prefer UID, else its name
            if isinstance(tx_id, pd.Series):
                if 'UID' in tx_id:
                    return str(tx_id.get('UID'))
                # Fall back to index label if available
                return str(getattr(tx_id, 'name', '')) or None
            # If a dict-like with UID
            if isinstance(tx_id, dict):
                if 'UID' in tx_id:
                    return str(tx_id.get('UID'))
                # Try common reference fields
                for k in ['Ext. Ref. Nbr.', 'Document Ref.', 'Orig. Doc. Number']:
                    if k in tx_id and tx_id[k]:
                        return str(tx_id[k])
                return None
            # Primitive
            return str(tx_id)
        except Exception:
            return None

    def _format_match_row(self, match_result, is_group_match: bool) -> dict:
        """Format a match result into a row for Excel output"""
        # Get bank transaction data using transaction IDs
        bank_data = self._get_transaction_details(match_result.bank_tx_id, 'bank', is_group_match)
        company_data = self._get_transaction_details(match_result.company_tx_id, 'company', is_group_match)
        
        row = {
            # Bank data
            'Bank Statement Date': bank_data.get('date', ''),
            'Bank Transaction ID': bank_data.get('transaction_id', ''),
            'Bank Reference Number': bank_data.get('reference', ''),
            'Bank Description': bank_data.get('description', ''),
            'Bank Receipt': bank_data.get('receipt', ''),
            'Bank Disbursement': bank_data.get('disbursement', ''),
            
            # Company data
            'CSGP Transaction Date': company_data.get('date', ''),
            'CSGP Reference': company_data.get('reference', ''),
            'CSGP Module': company_data.get('module', ''),
            'CSGP Description': company_data.get('description', ''),
            'CSGP Receipt': company_data.get('receipt', ''),
            'CSGP Disbursement': company_data.get('disbursement', ''),
            
            # Analysis data
            'Amount Difference': match_result.amount_diff if hasattr(match_result, 'amount_diff') else '',
            'Date Difference': match_result.date_diff if hasattr(match_result, 'date_diff') else '',
            'Reason': (
                match_result.ai_explanation if hasattr(match_result, 'ai_explanation') and match_result.ai_explanation 
                else (match_result.explanation if hasattr(match_result, 'explanation') else '')
            ),
            'Confidence': match_result.ai_confidence if hasattr(match_result, 'ai_confidence') and match_result.ai_confidence is not None else match_result.match_score,
            'Match Type': match_result.match_type if hasattr(match_result, 'match_type') else '',
            'Bank_UID': match_result.bank_tx_id if hasattr(match_result, 'bank_tx_id') else '',
            'CSGP_UID': match_result.company_tx_id if hasattr(match_result, 'company_tx_id') else ''
        }
        
        return row
    
    def _get_transaction_details(self, tx_ids, data_type: str, is_group_match: bool) -> dict:
        """Get transaction details from original DataFrames using transaction IDs"""
        if tx_ids is None:
            return {}
        
        # Determine which DataFrame to use
        df = self.bank_df if data_type == 'bank' else self.company_df
        if df is None:
            return {}
        
        # Handle group matches (multiple IDs)
        if is_group_match and isinstance(tx_ids, list):
            combined_data = {
                'date': [],
                'transaction_id': [],
                'reference': [],
                'description': [],
                'receipt': [],
                'disbursement': [],
                'module': []
            }
            
            for raw_id in tx_ids:
                tx_id = self._normalize_tx_id(raw_id)
                if tx_id is None:
                    continue
                if tx_id in df.index:
                    row = df.loc[tx_id]
                    
                    # If duplicate index, df.loc returns a DataFrame; iterate rows
                    row_iterable = [row] if isinstance(row, pd.Series) else [r for _, r in row.iterrows()]
                    for r in row_iterable:
                        # Map DataFrame columns to our expected fields
                        if data_type == 'bank':
                            combined_data['date'].append(self._safe_str(r.get('Tran. Date', '')))
                            combined_data['transaction_id'].append(self._safe_str(r.get('Ext. Tran. ID', '')))
                            combined_data['reference'].append(self._safe_str(r.get('Ext. Ref. Nbr.', '')))
                            combined_data['description'].append(self._safe_str(r.get('Tran. Desc', '')))
                            receipt = self._safe_amount(r.get('Receipt', 0))
                            disbursement = self._safe_amount(r.get('Disbursement', 0))
                            combined_data['receipt'].append(self._safe_str(receipt) if receipt > 0 else '')
                            combined_data['disbursement'].append(self._safe_str(disbursement) if disbursement > 0 else '')
                        else:  # company
                            combined_data['date'].append(self._safe_str(r.get('Doc. Date', '')))
                            combined_data['transaction_id'].append(self._safe_str(r.get('Orig. Doc. Number', '')))
                            combined_data['reference'].append(self._safe_str(r.get('Document Ref.', '')))
                            combined_data['description'].append(self._safe_str(r.get('Description', '')))
                            combined_data['module'].append(self._safe_str(r.get('Module', '')))
                            receipt = self._safe_amount(r.get('Receipt', 0))
                            disbursement = self._safe_amount(r.get('Disbursement', 0))
                            combined_data['receipt'].append(self._safe_str(receipt) if receipt > 0 else '')
                            combined_data['disbursement'].append(self._safe_str(disbursement) if disbursement > 0 else '')
            
            # Join with commas
            result = {
                'date': ', '.join([self._safe_str(x) for x in combined_data['date'] if x]),
                'transaction_id': ', '.join([self._safe_str(x) for x in combined_data['transaction_id'] if x]),
                'reference': ', '.join([self._safe_str(x) for x in combined_data['reference'] if x]),
                'description': ', '.join([self._safe_str(x) for x in combined_data['description'] if x]),
                'receipt': ', '.join([self._safe_str(x) for x in combined_data['receipt'] if x]),
                'disbursement': ', '.join([self._safe_str(x) for x in combined_data['disbursement'] if x])
            }
            
            if data_type == 'company':
                # Deduplicate module entries and remove empties
                seen = set(); mods = []
                for m in combined_data['module']:
                    s = self._safe_str(m)
                    if s and s not in seen:
                        mods.append(s); seen.add(s)
                result['module'] = ', '.join(mods)
            
            return result
        
        # Handle single transaction
        tx_id = tx_ids if not isinstance(tx_ids, list) else (tx_ids[0] if tx_ids else None)
        tx_id = self._normalize_tx_id(tx_id)
        if tx_id is not None and tx_id in df.index:
            row = df.loc[tx_id]
            
            # If duplicates (DataFrame), consolidate to CSV strings
            def consolidate(series_or_df, col):
                try:
                    if isinstance(series_or_df, pd.DataFrame):
                        return self._safe_str(series_or_df[col]) if col in series_or_df.columns else ''
                    return self._safe_str(series_or_df.get(col, ''))
                except Exception:
                    return ''

            if data_type == 'bank':
                receipt = self._safe_amount(consolidate(row, 'Receipt'))
                disbursement = self._safe_amount(consolidate(row, 'Disbursement'))
                return {
                    'date': consolidate(row, 'Tran. Date'),
                    'transaction_id': consolidate(row, 'Ext. Tran. ID'),
                    'reference': consolidate(row, 'Ext. Ref. Nbr.'),
                    'description': consolidate(row, 'Tran. Desc'),
                    'receipt': self._safe_str(receipt) if receipt > 0 else '',
                    'disbursement': self._safe_str(disbursement) if disbursement > 0 else ''
                }
            else:  # company
                receipt = self._safe_amount(consolidate(row, 'Receipt'))
                disbursement = self._safe_amount(consolidate(row, 'Disbursement'))
                return {
                    'date': consolidate(row, 'Doc. Date'),
                    'transaction_id': consolidate(row, 'Orig. Doc. Number'),
                    'reference': consolidate(row, 'Document Ref.'),
                    'description': consolidate(row, 'Description'),
                    'module': consolidate(row, 'Module'),
                    'receipt': self._safe_str(receipt) if receipt > 0 else '',
                    'disbursement': self._safe_str(disbursement) if disbursement > 0 else ''
                }
        
        return {}

    def save_unmatched_to_json(self, bank_path: str, company_path: str) -> None:
        if not self.config.SAVE_UNMATCHED_JSON:
            return
        ub, uc = self.get_unmatched_transactions()
        with open(bank_path, 'w', encoding='utf-8') as f:
            json.dump(ub.reset_index(drop=True).to_dict(orient='records'), f, ensure_ascii=False, indent=2)
        with open(company_path, 'w', encoding='utf-8') as f:
            json.dump(uc.reset_index(drop=True).to_dict(orient='records'), f, ensure_ascii=False, indent=2)

    def run_reconciliation(self, company_path: str, bank_path: str, enable_ai: bool, out_xlsx: Optional[str] = None) -> str:
        """Convenience method to run the full reconciliation flow from file paths.

        Args:
            company_path: Path to company statements JSON file.
            bank_path: Path to bank transactions JSON file.
            enable_ai: Toggle to enable/disable AI stages (matching + verification).
            out_xlsx: Optional explicit output Excel path. If not provided, a timestamped
                      file will be created under 'matching_results/'.

        Returns:
            The absolute path to the saved Excel file containing reconciliation results.
        """
        # Configure AI toggle
        try:
            self.config.ENABLE_AI = bool(enable_ai)
        except Exception:
            pass

        # Load data (expects JSON inputs as used by this orchestrator)
        if not isinstance(bank_path, str) or not isinstance(company_path, str):
            raise ValueError("bank_path and company_path must be strings")

        # Normalize to absolute paths for clarity
        bank_path_abs = os.path.abspath(bank_path)
        company_path_abs = os.path.abspath(company_path)

        # Basic existence check to help users
        if not os.path.exists(bank_path_abs):
            raise FileNotFoundError(f"Bank file not found: {bank_path_abs}")
        if not os.path.exists(company_path_abs):
            raise FileNotFoundError(f"Company file not found: {company_path_abs}")

        # Load and reconcile
        self.load_data(bank_path_abs, company_path_abs)
        _ = self.reconcile()

        # Determine output path
        if out_xlsx and isinstance(out_xlsx, str) and out_xlsx.strip():
            out_path = out_xlsx
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            out_path = os.path.join("matching_results", f"unified_results_{ts}.xlsx")

        # Ensure directory exists and save
        out_dir = os.path.dirname(out_path) or '.'
        os.makedirs(out_dir, exist_ok=True)
        self.save_results_to_excel(out_path)

        return os.path.abspath(out_path)

    def _call_openrouter_api(self, prompt: str, api_key: str) -> Optional[Dict[str, Any]]:
        """Call OpenRouter API for AI verification"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        
        models = list(getattr(self.config, 'OPENROUTER_MODELS', []) or [])
        if not models:
            self.logger.debug("No OPENROUTER_MODELS configured; skipping remote AI call and using local scoring only.")
            return None
        
        for model in models:
            try:
                data = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": int(getattr(self.config, 'MAX_TOKENS', 512)),
                    "temperature": 0.0
                }
                
                resp = requests.post(
                    getattr(self.config, 'OPENROUTER_API_URL', 'https://openrouter.ai/api/v1/chat/completions'),
                    headers=headers, 
                    json=data, 
                    timeout=60
                )
                
                if resp.status_code == 429:
                    # Rate limited, try next model
                    self.logger.debug(f"Rate limited on model {model}, trying next...")
                    time.sleep(5)
                    continue
                
                if resp.status_code != 200:
                    self.logger.debug(f"API error {resp.status_code} for model {model}: {resp.text}")
                    continue
                    
                result = resp.json()
                content = result["choices"][0]["message"]["content"]
                # Capture token usage if provided by API
                try:
                    usage = result.get("usage", {}) if isinstance(result, dict) else {}
                    prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
                    completion_tokens = int(usage.get("completion_tokens", 0) or 0)
                    # Some providers expose only total_tokens
                    if (prompt_tokens == 0 and completion_tokens == 0) and "total_tokens" in usage:
                        # Best-effort split: attribute all to prompt if no split is provided
                        total_tokens = int(usage.get("total_tokens", 0) or 0)
                        prompt_tokens = total_tokens
                        completion_tokens = 0
                    self._token_in_total += prompt_tokens
                    self._token_out_total += completion_tokens
                    self._token_calls += 1
                    self._token_logs.append({"in": prompt_tokens, "out": completion_tokens})
                except Exception:
                    pass
                
                # Parse JSON response
                parsed = self._safe_parse_json(content)
                if isinstance(parsed, dict) and 'is_valid' in parsed and 'confidence' in parsed and 'reason' in parsed:
                    self.logger.debug(f"AI verification successful with model {model}")
                    return {
                        'is_valid': bool(parsed['is_valid']),
                        'confidence': float(parsed['confidence']),
                        'reason': str(parsed['reason'])
                    }
                else:
                    self.logger.debug(f"Invalid response format from model {model}: {content}")
                    
            except Exception as e:
                self.logger.debug(f"OpenRouter API call failed for model {model}: {e}")
                continue
                
        return None

    def _safe_parse_json(self, content: str) -> Optional[Dict[str, Any]]:
        """Safely parse JSON content with fallback"""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Try to extract JSON from markdown code blocks
            import re
            json_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_match:
                try:
                    return json.loads(json_match.group(1))
                except json.JSONDecodeError:
                    pass
            return None


# =============================
# Convenience function
# =============================

def reconcile_unified(
    bank_json_path: str,
    company_json_path: str,
    out_xlsx: str,
    enable_ai: Optional[bool] = None,
    enable_group_matching: Optional[bool] = None,
    bank_name: str = "",
    enable_bulk_eft: Optional[bool] = None,
    bulk_eft_allow_any_bank: Optional[bool] = None,
    force_remote_verify: Optional[bool] = None,
    debug_log_skips: Optional[bool] = None,
    log_level: Optional[str] = "DEBUG",
    enable_ai_matching: Optional[bool] = False,
    enable_ai_verification: Optional[bool] = None,
):
    """Run reconciliation and return the path to the output Excel.

    Args:
        bank_json_path: Path to bank transactions JSON.
        company_json_path: Path to company statements JSON.
        out_xlsx: Output path directive. Behaviors:
            - "": auto-generate under 'matching_results/'
            - directory path (existing or ending with separator): create a timestamped file inside
            - file path: used as-is ('.xlsx' appended if missing)
        enable_ai: Optional toggle to enable/disable AI stage; if None, config default is used.
        bank_name: Optional bank code to influence filename when auto-generating (e.g. BIMB001).
    Returns:
        Absolute path to the saved Excel file with matched/unmatched sheets.
    """
    # Initialize observability and per-run tee logging
    correlation_id = f"run-{datetime.utcnow().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    run_log_dir = os.path.join("logs", "runs")
    run_log_path = os.path.join(run_log_dir, f"{correlation_id}.log")

    # Attach tee + file logging handler for this run
    tee_cm = TeeStdStreams(run_log_path)
    file_handler = None
    root_logger = logging.getLogger()
    try:
        tee_cm.__enter__()
        # Root logger to file as well
        try:
            file_handler = logging.FileHandler(run_log_path, encoding='utf-8')
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s'))
            root_logger.addHandler(file_handler)
            # Ensure we capture everything
            if root_logger.level > logging.DEBUG:
                root_logger.setLevel(logging.DEBUG)
        except Exception as _e:
            print(f"[WARN] Could not attach file handler to logger: {_e}")

        print(f"[RUN] Detailed log for this run will be written to: {run_log_path}")

        # Validate input paths early
        if not isinstance(bank_json_path, str) or not os.path.isfile(bank_json_path):
            raise DataValidationError(f"Bank JSON path does not exist or is not a file: {bank_json_path}")
        if not isinstance(company_json_path, str) or not os.path.isfile(company_json_path):
            raise DataValidationError(f"Company JSON path does not exist or is not a file: {company_json_path}")

        overrides: Dict[str, Any] = {}
        if enable_ai is not None:
            overrides["ENABLE_AI"] = enable_ai
        if enable_group_matching is not None:
            overrides["ENABLE_GROUP_MATCHING"] = bool(enable_group_matching)
        if enable_bulk_eft is not None:
            overrides["ENABLE_BULK_EFT"] = bool(enable_bulk_eft)
        if bulk_eft_allow_any_bank is not None:
            overrides["BULK_EFT_ALLOW_ANY_BANK"] = bool(bulk_eft_allow_any_bank)
        if enable_ai_matching is not None:
            overrides["ENABLE_AI_MATCHING"] = bool(enable_ai_matching)
        if enable_ai_verification is not None:
            overrides["ENABLE_AI_VERIFICATION"] = bool(enable_ai_verification)
        if force_remote_verify is not None:
            overrides["AI_FORCE_REMOTE_VERIFY"] = bool(force_remote_verify)
        if debug_log_skips is not None:
            overrides["AI_DEBUG_LOG_SKIPS"] = bool(debug_log_skips)
        if log_level:
            overrides["LOG_LEVEL"] = str(log_level)
        try:
            config = UnifiedConfig.from_env(**overrides)
        except ConfigurationError:
            # Already appropriately typed, re-raise
            raise
        except Exception as e:
            raise ConfigurationError(f"Failed to construct configuration: {e}")

        # Observability instances
        audit = AuditLogger(config.AUDIT_LOG_ENABLED, config.AUDIT_LOG_PATH, logger)
        metrics = MetricsHook(config.METRICS_ENABLED, config.METRICS_BACKEND, config.METRICS_PATH, logger)
        audit.log_event("reconcile.start", {
            "correlation_id": correlation_id,
            "bank_json": bank_json_path,
            "company_json": company_json_path,
            "enable_ai": overrides.get("ENABLE_AI", None),
            "run_log": run_log_path,
        })
        metrics.incr("reconcile.start", 1, {"bank_name": (bank_name or "").strip()})

        # Carry forward bank_name so bank-specific logic can be gated
        try:
            if isinstance(bank_name, str):
                config.BANK_NAME = bank_name
        except Exception:
            pass
        engine = UnifiedReconciler(config=config)
        try:
            with metrics.timing("reconcile.load_data", {"cid": correlation_id}):
                engine.load_data(bank_json_path, company_json_path)
            audit.log_event("reconcile.data_loaded", {"correlation_id": correlation_id})
        except Exception as e:
            audit.log_event("reconcile.error", {"correlation_id": correlation_id, "stage": "load_data", "error": str(e)})
            raise DataValidationError(f"Failed to load input JSON files: {e}")
        try:
            with metrics.timing("reconcile.core", {"cid": correlation_id}):
                results = engine.reconcile()
            audit.log_event("reconcile.completed", {"correlation_id": correlation_id, "results": len(results) if results else 0})
            metrics.observe("reconcile.results_count", float(len(results) if results else 0), {"cid": correlation_id})
        except Exception as e:
            audit.log_event("reconcile.error", {"correlation_id": correlation_id, "stage": "reconcile", "error": str(e)})
            raise ReconciliationError(f"Reconciliation failed: {e}")

        # Determine output path and save
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Build default filename, honoring bank_name when provided
        bn = (bank_name or "").strip()
        # sanitize bank name to safe uppercase alnum/_/-
        bn_sanitized = re.sub(r"[^A-Za-z0-9_\-]", "", bn).upper()
        if bn_sanitized:
            default_filename = f"MATCHLIST_{bn_sanitized}_{ts}.xlsx"
        else:
            default_filename = f"unified_results_{ts}.xlsx"
        if isinstance(out_xlsx, str) and out_xlsx.strip():
            candidate = out_xlsx.strip()
            # If points to an existing directory or clearly a directory path, place default filename inside
            if os.path.isdir(candidate) or candidate.endswith(os.sep):
                out_path = os.path.join(candidate, default_filename)
            else:
                root, ext = os.path.splitext(candidate)
                if ext.lower() != ".xlsx":
                    # If no/other extension, append .xlsx
                    out_path = candidate + ".xlsx"
                else:
                    out_path = candidate
        else:
            out_path = os.path.join("matching_results", default_filename)

        try:
            with metrics.timing("reconcile.export", {"cid": correlation_id}):
                os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
                engine.save_results_to_excel(out_path)
            audit.log_event("reconcile.exported", {"correlation_id": correlation_id, "out_path": out_path})
        except Exception as e:
            audit.log_event("reconcile.error", {"correlation_id": correlation_id, "stage": "export", "error": str(e)})
            raise ExportError(f"Failed to export results to Excel: {e}")
        return os.path.abspath(out_path)
    finally:
        # Detach file handler and close
        try:
            if file_handler is not None:
                root_logger.removeHandler(file_handler)
                file_handler.flush()
                file_handler.close()
        except Exception:
            pass
        # Restore std streams
        try:
            tee_cm.__exit__(None, None, None)
        except Exception:
            pass


def reconcile_unified_uipath(
    bank_json_path: str,
    company_json_path: str,
    out_xlsx: str,
    enable_ai: Optional[bool] = None,
    bank_name: str = "",
    enable_bulk_eft: Optional[bool] = None,
    bulk_eft_allow_any_bank: Optional[bool] = None,
    force_remote_verify: Optional[bool] = None,
    debug_log_skips: Optional[bool] = None,
    log_level: Optional[str] = "DEBUG",
    enable_ai_matching: Optional[bool] = False,
    enable_ai_verification: Optional[bool] = None,
) -> str:
    """UiPath-friendly wrapper for reconciliation.

    Differences from reconcile_unified():
    - Does NOT tee stdout/stderr or attach additional logging handlers (avoids UiPath hangs)
    - Disables tqdm progress bars via env var TQDM_DISABLE=1
    - Accepts string-like booleans and coerces them safely
    - Returns the absolute output path on success (same as reconcile_unified)
    - Raises the same typed exceptions on failure (DataValidationError, ConfigurationError, ReconciliationError, ExportError)
    - Uses the same matching/export logic via UnifiedReconciler directly
    """
    def _to_bool(v: Any) -> Optional[bool]:
        if isinstance(v, bool):
            return v
        if v is None:
            return None
        s = str(v).strip().lower()
        if s in ("1", "true", "yes", "y", "on"):  
            return True
        if s in ("0", "false", "no", "n", "off"): 
            return False
        return None

    try:
        # Minimize interactive/TTY behavior
        os.environ["TQDM_DISABLE"] = "1"
        # Additionally, monkeypatch tqdm everywhere to a no-op to avoid any residual progress output
        try:
            class NoOpTqdm:
                def __init__(self, iterable=None, *args, **kwargs):
                    self.iterable = iterable
                def __iter__(self):
                    if self.iterable is None:
                        return iter(())
                    return iter(self.iterable)
                def update(self, *args, **kwargs):
                    return None
                def set_description(self, *args, **kwargs):
                    return None
                def set_postfix(self, *args, **kwargs):
                    return None
                @staticmethod
                def write(*args, **kwargs):
                    return None
                def close(self):
                    return None
                def __enter__(self):
                    return self
                def __exit__(self, exc_type, exc, tb):
                    return False
            # Replace any already-imported global symbol in this module
            globals()['tqdm'] = NoOpTqdm
        except Exception:
            pass
        try:
            import tqdm as _tqdm
            _tqdm.tqdm = NoOpTqdm
            try:
                import tqdm.auto as _tqdm_auto
                _tqdm_auto.tqdm = NoOpTqdm
            except Exception:
                pass
        except Exception:
            pass

        # Basic validation
        if not isinstance(bank_json_path, str) or not os.path.isfile(bank_json_path):
            raise DataValidationError(f"Bank JSON path does not exist or is not a file: {bank_json_path}")
        if not isinstance(company_json_path, str) or not os.path.isfile(company_json_path):
            raise DataValidationError(f"Company JSON path does not exist or is not a file: {company_json_path}")

        # Build overrides safely (also disable any internal progress/debug that might print)
        overrides: Dict[str, Any] = {}
        overrides["ENABLE_RESERVATION_PROGRESS"] = False
        overrides["ENABLE_RESERVATION_DEBUG"] = False
        overrides["RESERVATION_LOG_TO_CONSOLE"] = False
        e_ai = _to_bool(enable_ai)
        if e_ai is not None:
            overrides["ENABLE_AI"] = e_ai
        e_bulk = _to_bool(enable_bulk_eft)
        if e_bulk is not None:
            overrides["ENABLE_BULK_EFT"] = e_bulk
        e_any = _to_bool(bulk_eft_allow_any_bank)
        if e_any is not None:
            overrides["BULK_EFT_ALLOW_ANY_BANK"] = e_any
        e_aim = _to_bool(enable_ai_matching)
        if e_aim is not None:
            overrides["ENABLE_AI_MATCHING"] = e_aim
        e_aiv = _to_bool(enable_ai_verification)
        if e_aiv is not None:
            overrides["ENABLE_AI_VERIFICATION"] = e_aiv
        frv = _to_bool(force_remote_verify)
        if frv is not None:
            overrides["AI_FORCE_REMOTE_VERIFY"] = frv
        dls = _to_bool(debug_log_skips)
        if dls is not None:
            overrides["AI_DEBUG_LOG_SKIPS"] = dls
        if isinstance(log_level, str) and log_level:
            overrides["LOG_LEVEL"] = log_level

        try:
            config = UnifiedConfig.from_env(**overrides)
        except Exception as e:
            raise ConfigurationError(f"Failed to construct configuration: {e}")

        # Run reconciliation
        # Carry forward bank_name so bank-specific logic can be gated
        try:
            if isinstance(bank_name, str):
                config.BANK_NAME = bank_name
        except Exception:
            pass
        engine = UnifiedReconciler(config=config)
        try:
            engine.load_data(bank_json_path, company_json_path)
        except Exception as e:
            raise DataValidationError(f"Failed to load input JSON files: {e}")
        try:
            results = engine.reconcile()
        except Exception as e:
            raise ReconciliationError(f"Reconciliation failed: {e}")

        # Determine output path and save (mirror logic without prints)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        bn = (bank_name or "").strip()
        bn_sanitized = re.sub(r"[^A-Za-z0-9_\-]", "", bn).upper()
        default_filename = f"MATCHLIST_{bn_sanitized}_{ts}.xlsx" if bn_sanitized else f"unified_results_{ts}.xlsx"
        if isinstance(out_xlsx, str) and out_xlsx.strip():
            candidate = out_xlsx.strip()
            if os.path.isdir(candidate) or candidate.endswith(os.sep):
                out_path = os.path.join(candidate, default_filename)
            else:
                root, ext = os.path.splitext(candidate)
                out_path = candidate + ".xlsx" if ext.lower() != ".xlsx" else candidate
        else:
            out_path = os.path.join("matching_results", default_filename)

        try:
            os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
            engine.save_results_to_excel(out_path)
        except Exception as e:
            raise ExportError(f"Failed to export results to Excel: {e}")
        return os.path.abspath(out_path)
    except Exception as e:
        # Propagate as a typed top-level reconciliation error
        raise ReconciliationError(f"Unexpected failure: {e}")


# =============================
# CLI entrypoint
# =============================
if False and __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Bank Reconciliation (traditional -> AI)")
    parser.add_argument("bank_json", nargs='?', default=None, help="Path to bank transactions JSON file")
    parser.add_argument("company_json", nargs='?', default=None, help="Path to company statements JSON file")

    # Outputs
    parser.add_argument("--out-xlsx", dest="out_xlsx", default="", help="Output XLSX path for matches + unmatched sheets")
    parser.add_argument("--out-unmatched-bank", dest="out_unmatched_bank", default="", help="Output JSON path for unmatched bank transactions")
    parser.add_argument("--out-unmatched-company", dest="out_unmatched_company", default="", help="Output JSON path for unmatched company transactions")

    # Toggles
    parser.add_argument("--enable-ai", dest="enable_ai", action="store_true", help="Enable AI stage")
    parser.add_argument("--disable-ai", dest="enable_ai", action="store_false", help="Disable AI stage")
    parser.set_defaults(enable_ai=False)
    # Composite stage removed

    parser.add_argument("--log-level", dest="log_level", default="INFO", help="Logging level (DEBUG, INFO, WARNING, ERROR)")

    # API key
    parser.add_argument("--open-router-key", dest="open_router_key", default=None, help="OpenRouter API key (or set OPEN_ROUTER_KEY env var)")

    args = parser.parse_args()

    # If not provided, use sensible defaults inside repo
    if not args.bank_json or not args.company_json:
        # Defaults requested by user
        # Previous defaults (commented out for reference):
        # default_bank = os.path.join("TestDataset", "SortedDataset", "Disbursement", "bank_statements.json")
        # default_company = os.path.join("TestDataset", "SortedDataset", "Disbursement", "company_statements.json")
        # New defaults: use fabricated_dataset
        # default_bank = os.path.join("fabricated_dataset", "bank_transactions.json")
        # default_company = os.path.join("fabricated_dataset", "company_statements.json")
        default_bank = os.path.join("TestDataset", "SortedDataset", "Filtered", "bank_statements.json")
        default_company = os.path.join("TestDataset", "SortedDataset", "Filtered", "company_statements.json")
        if not args.bank_json:
            args.bank_json = default_bank
        if not args.company_json:
            args.company_json = default_company
        print(f"No CLI paths provided. Using defaults: bank_json={args.bank_json}, company_json={args.company_json}")
        if not os.path.exists(args.bank_json) or not os.path.exists(args.company_json):
            print("Warning: One or both default files do not exist. Please supply paths explicitly.")

    cfg = UnifiedConfig.from_env(
        ENABLE_AI=args.enable_ai,
        LOG_LEVEL=args.log_level,
        OPEN_ROUTER_KEY=args.open_router_key or None,
    )

    engine = UnifiedReconciler(cfg)
    engine.load_data(args.bank_json, args.company_json)
    results = engine.reconcile()

    # Print brief summary
    print(f"Total matches: {len(results)}")
    ub, uc = engine.get_unmatched_transactions()
    print(f"Unmatched bank: {len(ub)} | Unmatched company: {len(uc)}")

    # Save outputs if requested
    if args.out_xlsx:
        out_path = args.out_xlsx
    else:
        # default into matching_results/ with timestamp
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join("matching_results", f"unified_results_{ts}.xlsx")
    try:
        # Debug: Check what's actually in results before saving
        match_types = {}
        for r in results:
            match_types[r.match_type] = match_types.get(r.match_type, 0) + 1
        
        bank_charges = sum(1 for r in results if r.match_type == 'bank_charge')
        print(f"About to save: {len(results)} total results")
        
        print(f"Match types: {match_types}")
        
        engine.save_results_to_excel(out_path)
        print(f"Saved results to {out_path}")
        
        # Verify what was actually saved (sum across accepted and rejected sheets)
        try:
            import pandas as pd
            saved_bank_charges = 0
            for sheet in ('matches_accepted', 'matches_rejected'):
                try:
                    df = pd.read_excel(out_path, sheet_name=sheet)
                except Exception:
                    continue
                saved_bank_charges += len(df[df['match_type'] == 'bank_charge'])
            print(f"Verified in Excel - Bank charges: {saved_bank_charges}")
        except Exception as verify_err:
            print(f"Warning: could not verify saved Excel sheets: {verify_err}")
        
    except Exception as e:
        print(f"Warning: could not save XLSX results: {e}")

    if args.out_unmatched_bank and args.out_unmatched_company:
        try:
            engine.save_unmatched_to_json(args.out_unmatched_bank, args.out_unmatched_company)
            print(f"Saved unmatched JSON to {args.out_unmatched_bank} and {args.out_unmatched_company}")
        except Exception as e:
            print(f"Warning: could not save unmatched JSON: {e}")
