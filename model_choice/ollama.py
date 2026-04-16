"""Ollama lifecycle management -- auto-start, model loading, health recovery.

Three responsibilities:
1. If ollama is not running, start it (via systemd or direct)
2. If the configured model isn't loaded, pull it
3. If ollama is unhealthy, restart it
"""

import json
import os
import shutil
import subprocess
import time
import urllib.request
import urllib.error
import logging
from typing import Optional

logger = logging.getLogger("model_choice.ollama")

DEFAULT_API_BASE = "http://localhost:11434"
STARTUP_TIMEOUT = 30  # seconds to wait for ollama to come up
HEALTH_TIMEOUT = 5    # seconds for health check ping
PULL_TIMEOUT = 300    # seconds for model pull


def _api_base(config_api_base: Optional[str] = None) -> str:
    return config_api_base or DEFAULT_API_BASE


def health_check(api_base: Optional[str] = None) -> bool:
    """Ping ollama /api/tags. Returns True if responding."""
    base = _api_base(api_base)
    try:
        urllib.request.urlopen(f"{base}/api/tags", timeout=HEALTH_TIMEOUT)
        return True
    except Exception:
        return False


def list_models(api_base: Optional[str] = None) -> list[str]:
    """List locally available ollama model names."""
    base = _api_base(api_base)
    try:
        resp = urllib.request.urlopen(f"{base}/api/tags", timeout=HEALTH_TIMEOUT)
        data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []


def model_loaded(model: str, api_base: Optional[str] = None) -> bool:
    """Check if a specific model is available locally.

    Handles both 'ollama/qwen2.5-coder:14b' (litellm format) and
    plain 'qwen2.5-coder:14b'.
    """
    # Strip ollama/ prefix if present
    name = model.split("/", 1)[-1] if "/" in model else model

    available = list_models(api_base)

    # Exact match
    if name in available:
        return True

    # Match without tag (e.g. 'qwen2.5-coder' matches 'qwen2.5-coder:14b')
    base_name = name.split(":")[0]
    for m in available:
        if m.split(":")[0] == base_name:
            return True

    # Match with tag against base names (e.g. 'qwen2.5-coder:latest' check)
    if ":latest" in name:
        plain = name.replace(":latest", "")
        if plain in available:
            return True

    return False


def pull_model(model: str, timeout: int = PULL_TIMEOUT) -> bool:
    """Pull a model via `ollama pull`. Returns True on success."""
    name = model.split("/", 1)[-1] if "/" in model else model
    ollama_bin = _find_binary()
    if not ollama_bin:
        logger.error("ollama binary not found, cannot pull model")
        return False

    logger.info(f"Pulling model {name}...")
    try:
        result = subprocess.run(
            [ollama_bin, "pull", name],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode == 0:
            logger.info(f"Model {name} pulled successfully")
            return True
        else:
            logger.error(f"Pull failed: {result.stderr.strip()}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"Pull timed out after {timeout}s")
        return False
    except Exception as e:
        logger.error(f"Pull error: {e}")
        return False


def start_ollama(timeout: int = STARTUP_TIMEOUT) -> bool:
    """Start ollama via systemd user service, falling back to direct launch.

    Returns True if ollama is running after the attempt.
    """
    # Try systemd first
    if _has_systemd_service():
        logger.info("Starting ollama via systemd...")
        try:
            subprocess.run(
                ["systemctl", "--user", "start", "ollama"],
                capture_output=True, timeout=10,
            )
            return _wait_for_health(timeout)
        except Exception as e:
            logger.warning(f"systemd start failed: {e}")

    # Fallback: direct launch
    ollama_bin = _find_binary()
    if not ollama_bin:
        logger.error("ollama binary not found")
        return False

    logger.info("Starting ollama directly...")
    try:
        subprocess.Popen(
            [ollama_bin, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return _wait_for_health(timeout)
    except Exception as e:
        logger.error(f"Direct start failed: {e}")
        return False


def restart_ollama(timeout: int = STARTUP_TIMEOUT) -> bool:
    """Restart ollama (systemd or kill+start)."""
    if _has_systemd_service():
        logger.info("Restarting ollama via systemd...")
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "ollama"],
                capture_output=True, timeout=10,
            )
            return _wait_for_health(timeout)
        except Exception as e:
            logger.warning(f"systemd restart failed: {e}")

    # Kill and restart
    logger.info("Killing ollama process...")
    _kill_ollama()
    time.sleep(2)
    return start_ollama(timeout)


def ensure_running(
    model: Optional[str] = None,
    api_base: Optional[str] = None,
    auto_start: bool = True,
    auto_pull: bool = True,
) -> bool:
    """Main entry point: ensure ollama is running and model is loaded.

    1. Check health -> if down, start
    2. Check model -> if missing, pull
    3. Final health check

    Returns True if ollama is healthy and model is loaded.
    """
    # Step 1: Health check, start if needed
    if not health_check(api_base):
        if not auto_start:
            return False
        if not start_ollama():
            return False

    # Step 2: Model check, pull if needed
    if model and not model_loaded(model, api_base):
        if not auto_pull:
            return False
        if not pull_model(model):
            return False

    # Step 3: Final check
    return health_check(api_base)


def recover(api_base: Optional[str] = None) -> bool:
    """Attempt full recovery: restart ollama.

    Called when ollama is responding but misbehaving (e.g. model
    load failures, GPU errors, corrupted state).
    """
    logger.info("Attempting ollama recovery...")
    return restart_ollama()


# ---- internal helpers ----

def _find_binary() -> Optional[str]:
    """Find ollama binary."""
    # Check PATH
    path = shutil.which("ollama")
    if path:
        return path
    # Check common locations
    for loc in [
        os.path.expanduser("~/.local/bin/ollama"),
        "/usr/local/bin/ollama",
        "/usr/bin/ollama",
    ]:
        if os.path.isfile(loc) and os.access(loc, os.X_OK):
            return loc
    return None


def _has_systemd_service() -> bool:
    """Check if ollama is managed by systemd user service."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "status", "ollama"],
            capture_output=True, timeout=5,
        )
        # returncode 0 = active, 3 = inactive (but service exists), others = no service
        return result.returncode in (0, 3)
    except Exception:
        return False


def _wait_for_health(timeout: int) -> bool:
    """Poll health check until ollama responds or timeout."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if health_check():
            return True
        time.sleep(1)
    return False


def _kill_ollama():
    """Kill ollama processes."""
    try:
        subprocess.run(
            ["pkill", "-f", "ollama serve"],
            capture_output=True, timeout=5,
        )
    except Exception:
        pass
