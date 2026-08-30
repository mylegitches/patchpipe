"""Filesystem paths for POD HD device data."""

from __future__ import annotations

from pathlib import Path


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").exists():
            return parent
    return here.parents[4]


REPO_ROOT = repo_root()
DATA_DIR = REPO_ROOT / "data" / "pod_hd"
PATCHES_DIR = REPO_ROOT / "patches"
