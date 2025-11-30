from pathlib import Path
import os


def get_downloads_dir() -> Path:
    """Return the resolved downloads directory, creating it if needed."""
    env_dir = os.getenv("SAVE_DIRECTORY")
    base_dir = Path(env_dir) if env_dir else Path(__file__).resolve().parent.parent / "Downloads"
    base_dir.mkdir(parents=True, exist_ok=True)
    return base_dir


def get_email_attachment_dir(message_id: str) -> Path:
    """Return a dedicated folder for email attachments for a message id."""
    base = get_downloads_dir() / "email_attachments" / message_id
    base.mkdir(parents=True, exist_ok=True)
    return base
