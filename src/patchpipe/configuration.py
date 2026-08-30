"""Shared Patchpipe configuration helpers."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Mapping

PATCHPIPE_KEYS = (
    "PATCHPIPE_LLM_API_KEY",
    "PATCHPIPE_LLM_BASE_URL",
    "PATCHPIPE_LLM_MODEL",
    "PATCHPIPE_OUTPUT_DIR",
)

JUNO_KEYS = (
    "PATCHMAKER_LLM_API_KEY",
    "PATCHMAKER_LLM_BASE_URL",
    "PATCHMAKER_LLM_MODEL",
)

POD_HD_KEYS = (
    "AI_BASE_URL",
    "AI_API_KEY",
    "AI_MODEL",
    "OUTPUT_DIR",
    "DEFAULT_TEMPLATE",
)

ALL_MANAGED_KEYS = PATCHPIPE_KEYS + JUNO_KEYS + POD_HD_KEYS


def local_env_path() -> Path:
    override = os.environ.get("PATCHPIPE_ENV_FILE")
    return Path(override).expanduser().resolve() if override else Path.cwd().joinpath(".env").resolve()


def read_local_env(path: Path | None = None) -> dict[str, str]:
    target = path or local_env_path()
    if not target.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in target.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, raw_value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        value = raw_value.strip()
        if value.startswith('"'):
            try:
                parsed = json.loads(value)
                value = parsed if isinstance(parsed, str) else value
            except json.JSONDecodeError:
                pass
        elif len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            value = value[1:-1]
        values[name] = value
    return values


def read_llm_value(*names: str) -> str | None:
    env = {**read_local_env(), **{k: v for k, v in os.environ.items() if k in ALL_MANAGED_KEYS}}
    for name in names:
        value = env.get(name)
        if value:
            return value
    return None


def save_llm_configuration(
    *,
    base_url: str,
    model: str,
    api_key: str,
    output_dir: str | None = None,
) -> Path:
    values = {
        "PATCHPIPE_LLM_API_KEY": api_key,
        "PATCHPIPE_LLM_BASE_URL": base_url,
        "PATCHPIPE_LLM_MODEL": model,
        "PATCHMAKER_LLM_API_KEY": api_key,
        "PATCHMAKER_LLM_BASE_URL": base_url,
        "PATCHMAKER_LLM_MODEL": model,
        "AI_BASE_URL": base_url,
        "AI_API_KEY": api_key,
        "AI_MODEL": model,
    }
    if output_dir is not None:
        values["PATCHPIPE_OUTPUT_DIR"] = output_dir
        values["OUTPUT_DIR"] = output_dir
    return update_local_env(values)


def update_local_env(values: Mapping[str, str], path: Path | None = None) -> Path:
    target = path or local_env_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    existing = target.read_text(encoding="utf-8").splitlines() if target.exists() else []
    remaining = dict(values)
    written: set[str] = set()
    output: list[str] = []
    for line in existing:
        stripped = line.strip()
        name = stripped.split("=", 1)[0].removeprefix("export ").strip() if "=" in stripped else ""
        if name in values:
            if name not in written:
                output.append(f"{name}={json.dumps(values[name])}")
                remaining.pop(name, None)
                written.add(name)
        else:
            output.append(line)
    if output and output[-1]:
        output.append("")
    output.extend(f"{name}={json.dumps(value)}" for name, value in remaining.items())
    content = "\n".join(output).rstrip() + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="\n", dir=target.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(content)
    try:
        os.chmod(temporary, 0o600)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return target
