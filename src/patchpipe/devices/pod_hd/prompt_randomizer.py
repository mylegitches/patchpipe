"""Guitar and amp sound-description vocabulary and coherent prompt generation."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .paths import DATA_DIR

_DATA_PATH = DATA_DIR / "prompt_bank.json"

with _DATA_PATH.open(encoding="utf-8") as handle:
    GUITAR_SOUND_ATTRIBUTES: Mapping[str, tuple[str, ...]] = {
        key: tuple(values) for key, values in json.load(handle).items()
    }

PROMPT_DIMENSIONS = (
    "tone_role",
    "mood",
    "tonal_character",
    "genre_era",
    "artist_vibe",
    "amp_vibe",
    "cab_character",
    "drive_level",
    "eq_character",
    "playing_style",
    "instrument",
    "picking_attack",
    "distortion_chain",
    "modulation",
    "delay_space",
    "reverb_room",
    "dynamics_gate",
    "frequency_focus",
    "texture",
    "mix_context",
    "intensity",
)

ROLE_CONSTRAINTS: Mapping[str, Mapping[str, tuple[str, ...]]] = {
    "bass": {
        "instrument": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["instrument"] if "bass" in v.lower()),
        "drive_level": (
            "clean with no drive", "light crunch", "amp gain at noon", "direct bass with light drive",
            "bass overdrive for grit", "bass fuzz for synth-like", "transparent boost only", "amp-like pedal drive",
        ),
        "cab_character": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["cab_character"] if "bass" in v.lower() or "DI" in v or "direct" in v.lower()),
        "playing_style": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["playing_style"] if "bass" in v.lower() or "finger" in v.lower() or "pick" in v.lower()),
        "reverb_room": ("dry and intimate", "short room reverb", "subtle room only", "medium hall live", "plate reverb shine"),
    },
    "clean": {
        "drive_level": (
            "clean with no drive", "clean with just a hint of hair", "barely breaking up",
            "edge-of-breakup dynamics", "transparent boost only", "just-clean", "almost-clean",
        ),
        "distortion_chain": (
            "a clean amp with only one drive pedal", "a dirty amp with no pedals", "a transparent boost",
            "a pedal platform plus amp", "a amp model with amp-only saturation", "no gate at all",
        ),
    },
    "metal": {
        "drive_level": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["drive_level"] if any(k in v for k in ("gain", "high", "sat", "thrash", "metal", "djent", "chainsaw"))),
        "dynamics_gate": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["dynamics_gate"] if "gate" in v or "tight" in v or "metal" in v),
        "eq_character": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["eq_character"] if "scoop" in v or "tight" in v or "metal" in v or "djent" in v),
    },
    "jazz": {
        "drive_level": ("clean with no drive", "barely breaking up", "edge-of-breakup dynamics", "just-clean", "almost-clean"),
        "tonal_character": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["tonal_character"] if v in ("warm", "dark", "smooth", "round", "woody", "hollow", "creamy", "silky", "vintage", "jazz")),
        "reverb_room": ("short room reverb", "plate reverb shine", "subtle room only", "dry and intimate", "chamber warmth"),
    },
    "ambient": {
        "delay_space": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["delay_space"] if v != "no delay"),
        "reverb_room": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["reverb_room"] if "long" in v or "ambient" in v or "hall" in v or "shimmer" in v or "infinite" in v),
        "modulation": tuple(v for v in GUITAR_SOUND_ATTRIBUTES["modulation"] if v != "no modulation"),
    },
}


@dataclass(frozen=True, slots=True)
class RandomizedPrompt:
    prompt: str
    attributes: Mapping[str, str]


def vocabulary_count() -> int:
    return sum(len(values) for values in GUITAR_SOUND_ATTRIBUTES.values())


def _options_for_role(role: str, category: str) -> tuple[str, ...]:
    role_lower = role.casefold()
    for keyword, constraints in ROLE_CONSTRAINTS.items():
        if keyword in role_lower and category in constraints:
            return constraints[category]
    return GUITAR_SOUND_ATTRIBUTES[category]


def randomize_prompt(rng: random.Random | None = None) -> RandomizedPrompt:
    """Combine complementary attribute dimensions into a ready-to-use tone prompt."""
    chooser = rng or random.SystemRandom()
    role = chooser.choice(GUITAR_SOUND_ATTRIBUTES["tone_role"])
    selected = {"tone_role": role}
    for key in PROMPT_DIMENSIONS:
        if key == "tone_role":
            continue
        selected[key] = chooser.choice(_options_for_role(role, key))
    prompt = (
        f"Design a {selected['mood']}, {selected['tonal_character']} {selected['tone_role']} "
        f"with a {selected['genre_era']} character, inspired by {selected['artist_vibe']}. "
        f"Start from {selected['amp_vibe']} through {selected['cab_character']} at {selected['drive_level']}. "
        f"Shape the EQ for {selected['eq_character']} while playing {selected['playing_style']} on "
        f"{selected['instrument']} with {selected['picking_attack']}. "
        f"Use {selected['distortion_chain']}, {selected['modulation']}, {selected['delay_space']}, "
        f"and {selected['reverb_room']}. Keep dynamics {selected['dynamics_gate']} with "
        f"{selected['frequency_focus']} and a {selected['texture']} texture so it sits "
        f"{selected['mix_context']} at {selected['intensity']} intensity."
    )
    return RandomizedPrompt(prompt=prompt, attributes=selected)
