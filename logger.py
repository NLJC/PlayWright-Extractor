import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Create logs directory if it doesn't exist
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

# Create logs/runs directory if it doesn't exist
RUNS_LOG_DIR = os.path.join(LOG_DIR, "runs")
os.makedirs(RUNS_LOG_DIR, exist_ok=True)

# Get debug mode from environment variable
DEBUG_MODE = os.getenv("DEBUG_MODE", "false").lower() == "true"
DEFAULT_LOG_LEVEL = logging.DEBUG if DEBUG_MODE else logging.INFO

def setup_logger(name: str = "playwright_automation", log_level: int = None, run_specific: bool = True) -> logging.Logger:
    """
    Sets up a logger with rotating file handler and console handler.

    Args:
        name: Name of the logger
        log_level: Logging level (default: from DEBUG_MODE env variable)
        run_specific: If True, also logs to a run-specific file in logs/runs/ directory

    Returns:
        Configured logger instance
    """
    # Use environment variable if log_level not specified
    if log_level is None:
        log_level = DEFAULT_LOG_LEVEL

    logger = logging.getLogger(name)
    logger.setLevel(log_level)

    # clear handlers if they exist to avoid duplicates
    if logger.handlers:
        logger.handlers.clear()

    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # File Handler (Rotating) - Main log file
    # Rotates after 5MB, keeps 5 backup files
    log_file = os.path.join(LOG_DIR, f"{name}.log")
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5*1024*1024,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(log_level)

    # Add run-specific file handler to logs/runs/ directory
    if run_specific:
        timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
        run_log_file = os.path.join(RUNS_LOG_DIR, f"{name}-{timestamp}-{os.getpid()}.log")
        run_file_handler = logging.FileHandler(run_log_file, encoding='utf-8')
        run_file_handler.setFormatter(formatter)
        run_file_handler.setLevel(log_level)
        logger.addHandler(run_file_handler)
        print(f"[INFO] Logging to: {run_log_file}")
        if DEBUG_MODE:
            print(f"[INFO] Debug mode: ENABLED (log level: DEBUG)")
        else:
            print(f"[INFO] Debug mode: DISABLED (log level: INFO)")

    # Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler.setLevel(log_level)

    # Add handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger

# Global logger instance
logger = setup_logger()
