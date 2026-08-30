"""
patch_builder.py - programmatic read/write for Line 6 POD HD .hbe patch files.

All byte-offset knowledge lives in data/full_decoder.json (amp/cab/mic bytes,
the 8 FX block offsets, and the per-block-type parameter layout) and
data/decoder_table.json (the FX type/model ID catalog), both built up by
reverse-engineering real patches and a screen recording of Line 6 POD HD Edit.

This module is purely mechanical: it has no opinion about what a "good" tone
is for a given request. That judgment belongs to whatever fills in a
FxSlotSpec/amp params - a human, or an LLM call in ai_client.py.

Key constraint this module exists to enforce: large parts of the 4136-byte
.hbe format are still unreverse-engineered. You cannot safely turn on an FX
slot by just poking a type/model byte into a slot that was never a valid
block of that type - the unknown bytes around it may not be structured
correctly. So enabling a *new* FX type in a slot works by copying a whole
256-byte block from a REFERENCE patch that's already a confirmed-valid,
enabled block of that type, then overwriting only the model byte and the
parameters we do understand. See REFERENCE_BLOCKS below.
"""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .paths import DATA_DIR, PATCHES_DIR

NAME_OFFSET = 0x28
NAME_LENGTH = 16

AMP_MODEL_OFFSET = 0x53
AMP_ON_OFFSET = 0x58
CAB_MODEL_OFFSET = 0x253
CAB_ON_OFFSET = 0x25B
MIC_OFFSET = 0x1020

# Amp tone-stack knobs, as absolute byte offsets (big-endian float32, 0.0-1.0)
AMP_PARAM_OFFSETS = {
    "drive": 0x64,
    "bass": 0x78,
    "mid": 0x8C,
    "treble": 0xA0,
    "presence": 0xB4,
    "channel_volume": 0xC8,
}

# The 8 FX slot block starts, and the relative layout within each 256-byte block.
FX_BLOCK_OFFSETS = [0x450, 0x550, 0x650, 0x750, 0x850, 0x950, 0xA50, 0xB50]
FX_BLOCK_SIZE = 0x100
FX_TYPE_REL = 1
FX_MODEL_REL = 3
FX_ON_REL = 11
# Up to 5 float params per block, at these relative offsets. Which knob a given
# offset maps to is block-type-specific and only partially confirmed - see
# FX_PARAM_LABELS.
FX_PARAM_RELS = [0x14, 0x28, 0x3C, 0x50, 0x64]

# Confirmed (or best-effort, clearly marked) knob labels per FX type, in
# FX_PARAM_RELS order. `None` means "present but not confidently mapped yet -
# don't guess, leave it alone unless the caller passes a raw index."
FX_PARAM_LABELS = {
    "Dyn": ["thresh_or_sustain", "decay_or_level", None, None, None],
    "Dist": ["drive", "bass", "mid", "treble", "output"],
    "Delay": ["time", "feedback", "tone", None, "mix"],
    "Reverb": ["decay", "pre_delay", "tone", "mix", None],
    "Mod": ["rate", "depth", None, None, None],
    # Pre+EQ: only confirmed for the Studio EQ model, which reads as 5 bands
    # centered at 0.5 = flat (band order assumed Low->High, not fully verified).
    "Pre+EQ": ["low", "low_mid", "mid", "high_mid", "high"],
    "VolPan": ["level", None, None, None, None],
}

# Which patch file + slot index (0-based into FX_BLOCK_OFFSETS) is a confirmed
# *enabled* block of each FX type, safe to copy wholesale when turning on a
# type that isn't already active in the target slot. Wah/Filter/Pitch/FXLoop
# have no confirmed-valid enabled example anywhere in this project's patch
# library yet - building one from scratch risks a corrupt patch, so
# set_fx_slot() refuses those types until a real reference is captured.
REFERENCE_BLOCKS = {
    "Dyn": ("NeoPsych.hbe", 0),
    "Mod": ("NeoPsych.hbe", 2),
    "Dist": ("NeoPsych.hbe", 3),
    "Delay": ("NeoPsych.hbe", 4),
    "Reverb": ("NeoPsych.hbe", 5),
    "Pre+EQ": ("NeoPsych.hbe", 6),
    "VolPan": ("Bass.hbe", 7),
}
UNSUPPORTED_FX_TYPES = {"Wah", "Filter", "Pitch", "FXLoop"}


def _load_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


class Catalog:
    """Name <-> ID lookups for amp/cab/mic and FX type/model, loaded once."""

    def __init__(self, data_dir: Path = DATA_DIR):
        full = _load_json(data_dir / "full_decoder.json")
        self.amp_models: dict[int, str] = {int(k): v for k, v in full["amp"]["models"].items()}
        self.cab_models: dict[int, str] = {int(k): v for k, v in full["cab"]["models"].items()}
        self.mic_models: dict[int, str] = {int(k): v for k, v in full["mic"]["models"].items()}
        self.fx_types: dict[int, str] = {int(k): v for k, v in full["fx_blocks"]["types"].items()}
        self.fx_models: dict[str, dict[int, str]] = {
            t: {int(k): v for k, v in m.items()} for t, m in full["fx_blocks"]["models"].items()
        }
        self._amp_by_name = {v: k for k, v in self.amp_models.items()}
        self._cab_by_name = {v: k for k, v in self.cab_models.items()}
        self._mic_by_name = {v: k for k, v in self.mic_models.items()}
        self._fx_type_by_name = {v: k for k, v in self.fx_types.items()}

    def amp_id(self, name: str) -> int:
        return self._amp_by_name[name]

    def cab_id(self, name: str) -> int:
        return self._cab_by_name[name]

    def mic_id(self, name: str) -> int:
        return self._mic_by_name[name]

    def fx_type_id(self, type_name: str) -> int:
        return self._fx_type_by_name[type_name]

    def fx_model_id(self, type_name: str, model_name: str) -> int:
        by_name = {v: k for k, v in self.fx_models[type_name].items()}
        return by_name[model_name]


CATALOG = Catalog()


@dataclass
class FxSlotSpec:
    """What the caller wants slot N to be. `on=False` just disables the slot -
    every other field is ignored."""

    on: bool
    type: Optional[str] = None          # e.g. "Dist" - required if on=True
    model: Optional[str] = None         # e.g. "Screamer" - required if on=True
    params: dict[str, float] = field(default_factory=dict)  # label -> 0.0-1.0


class Patch:
    """An in-memory, mutable .hbe patch. Always start from a real template
    file (Patch.from_template) - never build one from a zero-filled buffer,
    since most of the 4136 bytes aren't reverse-engineered and a real patch
    already has valid structure everywhere we haven't decoded."""

    def __init__(self, data: bytearray):
        if len(data) != 4136:
            raise ValueError(f"expected a 4136-byte .hbe patch, got {len(data)} bytes")
        self.data = data

    @classmethod
    def from_template(cls, path: str | Path) -> "Patch":
        return cls(bytearray(Path(path).read_bytes()))

    @classmethod
    def from_library(cls, filename: str) -> "Patch":
        """Load one of the bundled reference/example patches from patches/."""
        return cls.from_template(PATCHES_DIR / filename)

    def save(self, path: str | Path) -> None:
        Path(path).write_bytes(bytes(self.data))

    # ---- name -----------------------------------------------------------

    @property
    def name(self) -> str:
        return self.data[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH].decode("ascii", "replace").strip()

    @name.setter
    def name(self, value: str) -> None:
        raw = value.encode("ascii")[:NAME_LENGTH]
        raw = raw + b" " * (NAME_LENGTH - len(raw))
        self.data[NAME_OFFSET:NAME_OFFSET + NAME_LENGTH] = raw

    # ---- amp/cab/mic ------------------------------------------------------

    def set_amp(self, model: str, cab: str, mic: str, on: bool = True) -> None:
        self.data[AMP_MODEL_OFFSET] = CATALOG.amp_id(model)
        self.data[AMP_ON_OFFSET] = 1 if on else 0
        self.data[CAB_MODEL_OFFSET] = CATALOG.cab_id(cab)
        self.data[CAB_ON_OFFSET] = 1 if on else 0
        self.data[MIC_OFFSET] = CATALOG.mic_id(mic)

    def disable_amp(self) -> None:
        """DI patch: no amp/cab modeling, tone shaped entirely by the FX chain."""
        self.data[AMP_ON_OFFSET] = 0
        self.data[CAB_ON_OFFSET] = 0

    def get_amp(self) -> Optional[dict]:
        if not self.data[AMP_ON_OFFSET]:
            return None
        return {
            "model": CATALOG.amp_models.get(self.data[AMP_MODEL_OFFSET]),
            "cab": CATALOG.cab_models.get(self.data[CAB_MODEL_OFFSET]),
            "mic": CATALOG.mic_models.get(self.data[MIC_OFFSET]),
            "params": self.get_amp_params(),
        }

    def set_amp_params(self, **kwargs: float) -> None:
        for label, value in kwargs.items():
            if label not in AMP_PARAM_OFFSETS:
                raise ValueError(f"unknown amp param {label!r}, expected one of {list(AMP_PARAM_OFFSETS)}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"amp param {label!r} must be in [0.0, 1.0], got {value}")
            off = AMP_PARAM_OFFSETS[label]
            self.data[off:off + 4] = struct.pack(">f", value)

    def get_amp_params(self) -> dict[str, float]:
        return {label: struct.unpack(">f", self.data[off:off + 4])[0]
                for label, off in AMP_PARAM_OFFSETS.items()}

    # ---- FX slots ---------------------------------------------------------

    def get_fx_slot(self, slot: int) -> dict:
        """slot is 1-8."""
        block = FX_BLOCK_OFFSETS[slot - 1]
        on = bool(self.data[block + FX_ON_REL])
        type_id = self.data[block + FX_TYPE_REL]
        model_id = self.data[block + FX_MODEL_REL]
        type_name = CATALOG.fx_types.get(type_id)
        model_name = CATALOG.fx_models.get(type_name, {}).get(model_id) if type_name else None
        labels = FX_PARAM_LABELS.get(type_name, [None] * 5)
        params = {}
        for rel, label in zip(FX_PARAM_RELS, labels):
            if label is None:
                continue
            val = struct.unpack(">f", self.data[block + rel:block + rel + 4])[0]
            params[label] = val
        return {"on": on, "type": type_name, "model": model_name, "params": params}

    def disable_fx_slot(self, slot: int) -> None:
        block = FX_BLOCK_OFFSETS[slot - 1]
        self.data[block + FX_ON_REL] = 0

    def set_fx_slot(self, slot: int, spec: FxSlotSpec) -> None:
        """slot is 1-8. Raises ValueError for fx types with no confirmed-valid
        reference block (see UNSUPPORTED_FX_TYPES)."""
        block = FX_BLOCK_OFFSETS[slot - 1]

        if not spec.on:
            self.data[block + FX_ON_REL] = 0
            return

        if spec.type in UNSUPPORTED_FX_TYPES:
            raise ValueError(
                f"no confirmed-valid enabled '{spec.type}' block exists in this project's "
                f"reference library yet - refusing to fabricate one, since an incorrectly "
                f"structured block risks a corrupt patch. Build one on real hardware and add "
                f"it to REFERENCE_BLOCKS before using this type."
            )

        current_type_id = self.data[block + FX_TYPE_REL]
        current_type_name = CATALOG.fx_types.get(current_type_id)
        if current_type_name != spec.type:
            # This slot isn't currently a valid block of the requested type -
            # copy one in wholesale from a confirmed-good reference patch
            # rather than trying to hand-craft the still-unreverse-engineered
            # parts of the block structure.
            ref_filename, ref_slot_index = REFERENCE_BLOCKS[spec.type]
            ref_data = Patch.from_library(ref_filename).data
            ref_block = FX_BLOCK_OFFSETS[ref_slot_index]
            self.data[block:block + FX_BLOCK_SIZE] = ref_data[ref_block:ref_block + FX_BLOCK_SIZE]

        self.data[block + FX_MODEL_REL] = CATALOG.fx_model_id(spec.type, spec.model)
        self.data[block + FX_ON_REL] = 1

        labels = FX_PARAM_LABELS.get(spec.type, [None] * 5)
        label_to_rel = {label: rel for rel, label in zip(FX_PARAM_RELS, labels) if label}
        for label, value in spec.params.items():
            if label not in label_to_rel:
                raise ValueError(f"no known param offset for {spec.type}/{label!r}")
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"param {label!r} must be in [0.0, 1.0], got {value}")
            rel = label_to_rel[label]
            self.data[block + rel:block + rel + 4] = struct.pack(">f", value)

    def dump(self) -> dict:
        """Full human-readable summary, handy for logging/debugging."""
        return {
            "name": self.name,
            "amp": self.get_amp(),
            "fx_slots": [self.get_fx_slot(i) for i in range(1, 9)],
        }


if __name__ == "__main__":
    # Smoke test: rebuild the Kyuss patch from Tight Grip.hbe and confirm the
    # result matches the shipped patches/Kyuss.hbe byte-for-byte.
    p = Patch.from_library("Tight Grip.hbe")
    p.name = "Kyuss"
    p.set_amp("Brit J-800", "4x12 XXL V-30", "421 Dynamic")
    p.set_amp_params(drive=0.65, bass=0.80, mid=0.65, treble=0.40, presence=0.45, channel_volume=0.75)
    p.set_fx_slot(1, FxSlotSpec(on=True, type="Dyn", model="Noise Gate",
                                 params={"thresh_or_sustain": 0.25, "decay_or_level": 0.20}))
    p.set_fx_slot(2, FxSlotSpec(on=True, type="Dist", model="Overdrive",
                                 params={"drive": 0.30, "bass": 0.55, "mid": 0.55, "treble": 0.45, "output": 0.55}))

    reference = (PATCHES_DIR / "Kyuss.hbe").read_bytes()
    if bytes(p.data) == reference:
        print("OK: rebuilt Kyuss.hbe matches the shipped reference byte-for-byte")
    else:
        diffs = [i for i in range(len(reference)) if p.data[i] != reference[i]]
        print(f"MISMATCH: {len(diffs)} differing bytes, first at offset {hex(diffs[0]) if diffs else None}")
