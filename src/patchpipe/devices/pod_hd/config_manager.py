"""Load, save, and apply app configuration (.env + session overrides)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = REPO_ROOT / ".env"
ENV_EXAMPLE_PATH = REPO_ROOT / ".env.example"

CONFIG_KEYS = (
    "AI_BASE_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "OUTPUT_DIR",
    "DEFAULT_TEMPLATE",
)


def app_root() -> Path:
    """Repo root when running from source; bundle root when frozen."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return REPO_ROOT


def writable_root() -> Path:
    """Directory for .env and user output when packaged as an exe."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return REPO_ROOT


def env_file_path() -> Path:
    return writable_root() / ".env"


def parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def format_env_file(values: dict[str, str]) -> str:
    lines = [
        "# POD HD Patch Maker configuration",
        "# Real environment variables always override this file.",
        "",
        "# --- AI endpoint (any OpenAI-compatible API) ---",
        f"AI_BASE_URL={values.get('AI_BASE_URL', '')}",
        f"AI_API_KEY={values.get('AI_API_KEY', '')}",
        f"AI_MODEL={values.get('AI_MODEL', '')}",
        "",
        "# --- App ---",
        f"OUTPUT_DIR={values.get('OUTPUT_DIR', '')}",
        f"DEFAULT_TEMPLATE={values.get('DEFAULT_TEMPLATE', 'Tight Grip.hbe')}",
        "",
    ]
    return "\n".join(lines)


def load_config() -> dict[str, str]:
    """Merge .env file with real environment (env vars win)."""
    file_values = parse_env_file(env_file_path())
    if not file_values and ENV_EXAMPLE_PATH.exists():
        file_values = parse_env_file(ENV_EXAMPLE_PATH)

    config: dict[str, str] = {}
    for key in CONFIG_KEYS:
        config[key] = os.environ.get(key) or file_values.get(key, "")

    if not config.get("OUTPUT_DIR"):
        config["OUTPUT_DIR"] = str(writable_root() / "output")
    if not config.get("DEFAULT_TEMPLATE"):
        config["DEFAULT_TEMPLATE"] = "Tight Grip.hbe"
    return config


def save_config(values: dict[str, str]) -> Path:
    """Persist settings to .env and apply them to the current process."""
    path = env_file_path()
    current = parse_env_file(path)
    current.update({k: values.get(k, "") for k in CONFIG_KEYS})
    path.write_text(format_env_file(current), encoding="utf-8")
    apply_config(current)
    return path


def apply_config(values: dict[str, str] | None = None) -> dict[str, str]:
    """Push config into os.environ for the running session."""
    config = values or load_config()
    for key in CONFIG_KEYS:
        val = config.get(key, "")
        if val:
            os.environ[key] = val
        elif key in os.environ:
            del os.environ[key]
    return config


def ensure_output_dir(config: dict[str, str] | None = None) -> Path:
    cfg = config or load_config()
    out = Path(cfg.get("OUTPUT_DIR") or writable_root() / "output")
    out.mkdir(parents=True, exist_ok=True)
    return out
