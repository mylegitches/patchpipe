"""
ai_client.py - the AI-agnostic bridge: turns a plain-English tone request
("Kyuss desert rock tone") into a validated patch spec, then hands that spec
to patch_builder.py to produce a real .hbe file.

Works against any OpenAI-compatible chat completions endpoint - OpenAI,
Ollama (local or Ollama Cloud), LM Studio, vLLM, Azure OpenAI, OpenRouter,
etc. Only three environment variables change per provider; no code changes:

    AI_BASE_URL   e.g. https://api.openai.com/v1
                       http://localhost:11434/v1   (local Ollama)
                       https://ollama.com/v1        (Ollama Cloud)
    AI_API_KEY
    AI_MODEL      e.g. gpt-4o-mini, minimax-m2.7:cloud, llama3.1

Copy .env.example to .env and fill those in - .env is gitignored, so a real
key placed there is never committed. Alternatively export the same three
vars in your shell.

The model never touches raw bytes: it only ever emits/validates a structured
JSON spec (amp/cab/mic + 8 FX slots). validate_spec() checks that spec
against the same catalogs patch_builder.py uses, and build_patch_from_spec()
is the only thing that writes bytes.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from .patch_builder import (
    AMP_PARAM_OFFSETS,
    CATALOG,
    FX_PARAM_LABELS,
    REFERENCE_BLOCKS,
    UNSUPPORTED_FX_TYPES,
    FxSlotSpec,
    Patch,
)
from .paths import REPO_ROOT
DEFAULT_TEMPLATE = "Tight Grip.hbe"
N_FX_SLOTS = 8
SUPPORTED_FX_TYPES = sorted(REFERENCE_BLOCKS.keys())


def _load_env_file(path: Path | None = None) -> None:
    """Tiny built-in .env loader so this stays dependency-free beyond `openai`.
    Only sets a variable if it isn't already set in the real environment, so
    real env vars always win over the file."""
    if path is None:
        path = Path.cwd() / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


def get_client():
    _load_env_file()
    base_url = os.environ.get("AI_BASE_URL")
    api_key = os.environ.get("AI_API_KEY")
    model = os.environ.get("AI_MODEL")
    if not (base_url and api_key and model):
        raise RuntimeError(
            "AI_BASE_URL / AI_API_KEY / AI_MODEL are not fully set. "
            "Copy .env.example to .env in the repo root and fill them in, "
            "or export them in your shell."
        )
    from openai import OpenAI  # imported lazily so patch_builder.py alone stays dependency-free

    return OpenAI(base_url=base_url, api_key=api_key), model


# ---------------------------------------------------------------------------
# System prompt - built from the same catalogs patch_builder.py enforces, so
# the two can't drift out of sync.
# ---------------------------------------------------------------------------

def _fx_catalog_text() -> str:
    lines = []
    for fx_type in SUPPORTED_FX_TYPES:
        models = sorted(CATALOG.fx_models.get(fx_type, {}).values())
        labels = [l for l in FX_PARAM_LABELS.get(fx_type, []) if l]
        lines.append(f"- {fx_type}: models = {models}; params (0.0-1.0 each) = {labels}")
    return "\n".join(lines)


def build_system_prompt() -> str:
    amp_models = sorted(CATALOG.amp_models.values())
    cab_models = sorted(CATALOG.cab_models.values())
    mic_models = sorted(CATALOG.mic_models.values())
    return f"""You design tones for a Line 6 POD HD guitar/bass modeler. Given a
plain-English request, respond with ONE JSON object describing a patch - no
prose, no markdown fences, just the JSON object.

Schema:
{{
  "patch_name": "<=16 chars",
  "amp": null | {{
    "model": "<one of AMP MODELS>",
    "cab": "<one of CAB MODELS>",
    "mic": "<one of MIC MODELS>",
    "drive": 0.0-1.0, "bass": 0.0-1.0, "mid": 0.0-1.0,
    "treble": 0.0-1.0, "presence": 0.0-1.0, "channel_volume": 0.0-1.0
  }},
  "fx_slots": [ <exactly {N_FX_SLOTS} entries, one per slot, in order> ]
}}

Use "amp": null for a DI patch with no amp/cab modeling (typical for bass
patches meant to be reamped later) - tone is then shaped entirely by the FX
chain. All 6 amp params are required whenever "amp" is not null.

Each entry in "fx_slots" is either:
  {{"on": false}}
or:
  {{"on": true, "type": "<FX TYPE>", "model": "<model for that type>",
    "params": {{"<param>": 0.0-1.0, ...}}}}
Only include params your FX TYPE actually has (see catalog below) - omit
ones you don't want to set rather than guessing a value for an unlisted one.

AMP MODELS: {amp_models}
CAB MODELS: {cab_models}
MIC MODELS: {mic_models}

FX TYPES (ONLY these are usable - no others exist in the reference library):
{_fx_catalog_text()}

Do not invent model names, amp/cab/mic names, or FX types outside these
lists - the result will be rejected and you'll be asked to fix it."""


# ---------------------------------------------------------------------------
# Validation - the same rules patch_builder.py itself would enforce, checked
# early so a bad spec gets a specific, fixable error fed back to the model.
# ---------------------------------------------------------------------------

def validate_spec(spec: dict) -> None:
    if not isinstance(spec, dict):
        raise ValueError("top-level response must be a JSON object")

    name = spec.get("patch_name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError("patch_name must be a non-empty string")

    amp = spec.get("amp")
    if amp is not None:
        if not isinstance(amp, dict):
            raise ValueError('"amp" must be null or an object')
        for field, catalog_values in (
            ("model", CATALOG.amp_models.values()),
            ("cab", CATALOG.cab_models.values()),
            ("mic", CATALOG.mic_models.values()),
        ):
            if amp.get(field) not in catalog_values:
                raise ValueError(f'amp.{field} {amp.get(field)!r} is not a known {field}')
        for param in AMP_PARAM_OFFSETS:
            val = amp.get(param)
            if not isinstance(val, (int, float)) or not 0.0 <= val <= 1.0:
                raise ValueError(f"amp.{param} must be a number in [0.0, 1.0], got {val!r}")

    fx_slots = spec.get("fx_slots")
    if not isinstance(fx_slots, list) or len(fx_slots) != N_FX_SLOTS:
        raise ValueError(f"fx_slots must be a list of exactly {N_FX_SLOTS} entries")

    for i, slot in enumerate(fx_slots, start=1):
        if not isinstance(slot, dict) or "on" not in slot:
            raise ValueError(f"fx_slots[{i}] must be an object with an \"on\" boolean")
        if not slot["on"]:
            continue
        fx_type = slot.get("type")
        if fx_type in UNSUPPORTED_FX_TYPES:
            raise ValueError(
                f"fx_slots[{i}].type {fx_type!r} has no confirmed-valid reference block - "
                f"use one of {SUPPORTED_FX_TYPES} instead, or set \"on\": false"
            )
        if fx_type not in SUPPORTED_FX_TYPES:
            raise ValueError(f"fx_slots[{i}].type {fx_type!r} is not a known FX type")
        valid_models = CATALOG.fx_models.get(fx_type, {}).values()
        if slot.get("model") not in valid_models:
            raise ValueError(f"fx_slots[{i}].model {slot.get('model')!r} is not valid for type {fx_type!r}")
        valid_params = {l for l in FX_PARAM_LABELS.get(fx_type, []) if l}
        for param, val in (slot.get("params") or {}).items():
            if param not in valid_params:
                raise ValueError(f"fx_slots[{i}] has no known param {param!r} for type {fx_type!r} (valid: {sorted(valid_params)})")
            if not isinstance(val, (int, float)) or not 0.0 <= val <= 1.0:
                raise ValueError(f"fx_slots[{i}].params.{param} must be a number in [0.0, 1.0], got {val!r}")


# ---------------------------------------------------------------------------
# LLM round trip
# ---------------------------------------------------------------------------

def request_patch_spec(user_request: str, max_retries: int = 3) -> dict:
    client, model = get_client()
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_request},
    ]
    last_error: Exception | None = None
    for _ in range(max_retries):
        resp = client.chat.completions.create(
            model=model,
            messages=messages,
            response_format={"type": "json_object"},
        )
        raw = resp.choices[0].message.content
        try:
            spec = json.loads(raw)
            validate_spec(spec)
            return spec
        except (json.JSONDecodeError, ValueError) as e:
            last_error = e
            messages.append({"role": "assistant", "content": raw})
            messages.append({"role": "user", "content": f"That was invalid: {e}. Return corrected JSON only."})
    raise RuntimeError(f"model failed to produce a valid patch spec after {max_retries} attempts: {last_error}")


# ---------------------------------------------------------------------------
# Spec -> bytes
# ---------------------------------------------------------------------------

def build_patch_from_spec(spec: dict, template: str = DEFAULT_TEMPLATE) -> Patch:
    validate_spec(spec)
    patch = Patch.from_library(spec.get("template", template))
    patch.name = spec["patch_name"]

    amp = spec.get("amp")
    if amp is None:
        patch.disable_amp()
    else:
        patch.set_amp(amp["model"], amp["cab"], amp["mic"])
        patch.set_amp_params(**{k: float(amp[k]) for k in AMP_PARAM_OFFSETS})

    for i, slot in enumerate(spec["fx_slots"], start=1):
        if slot["on"]:
            params = {k: float(v) for k, v in (slot.get("params") or {}).items()}
            patch.set_fx_slot(i, FxSlotSpec(on=True, type=slot["type"], model=slot["model"], params=params))
        else:
            patch.disable_fx_slot(i)

    return patch


def test_connection() -> str:
    """Verify the configured endpoint responds; returns the model name."""
    client, model = get_client()
    client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "ping"}],
        max_tokens=5,
    )
    return model


def generate_patch_file(
    user_request: str,
    *,
    template: str = DEFAULT_TEMPLATE,
    output_dir: str | Path | None = None,
) -> tuple[dict, Path]:
    """Generate a validated spec, build the .hbe, and return both."""
    spec = request_patch_spec(user_request)
    patch = build_patch_from_spec(spec, template)
    out_root = Path(output_dir) if output_dir else REPO_ROOT / "output"
    out_root.mkdir(parents=True, exist_ok=True)
    safe = "".join(ch if ch.isalnum() or ch in " -_" else "_" for ch in spec["patch_name"]).strip()
    safe = (safe or "output")[:32]
    out_path = out_root / f"{safe}.hbe"
    patch.save(out_path)
    return spec, out_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("request", help='plain-English tone request, e.g. "Kyuss desert rock tone"')
    parser.add_argument("--template", default=DEFAULT_TEMPLATE, help=f"base .hbe to start from (default: {DEFAULT_TEMPLATE})")
    parser.add_argument("-o", "--out", default="output.hbe", help="output .hbe path (default: output.hbe)")
    args = parser.parse_args()

    spec = request_patch_spec(args.request)
    print(json.dumps(spec, indent=2))
    patch = build_patch_from_spec(spec, args.template)
    patch.save(args.out)
    print(f"\nwrote {args.out}")


if __name__ == "__main__":
    main()
