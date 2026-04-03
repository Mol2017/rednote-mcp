import json
import os
from pathlib import Path
from typing import Any

from rednote_mcp.utils.logger import get_logger

logger = get_logger(__name__)

COOKIE_PATH = Path.home() / ".mcp" / "rednote" / "cookies.json"


def save_cookies(cookies: list[dict[str, Any]]) -> None:
    COOKIE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(COOKIE_PATH, "w", encoding="utf-8") as f:
        json.dump(cookies, f, ensure_ascii=False, indent=2)
    logger.info("Cookies saved to %s", COOKIE_PATH)


def load_cookies() -> list[dict[str, Any]] | None:
    if not COOKIE_PATH.exists():
        return None
    try:
        with open(COOKIE_PATH, "r", encoding="utf-8") as f:
            cookies = json.load(f)
        logger.info("Loaded %d cookies from %s", len(cookies), COOKIE_PATH)
        return cookies
    except Exception as e:
        logger.warning("Failed to load cookies: %s", e)
        return None


def clear_cookies() -> None:
    if COOKIE_PATH.exists():
        COOKIE_PATH.unlink()
        logger.info("Cookies cleared")
