# Patchpipe

Unified AI patch maker for multiple devices. Pick your hardware on the home screen, describe a sound in plain language, and get a validated patch saved locally.

## Supported devices

| Device | Output | Features |
|---|---|---|
| **Roland JUNO-DS** | JSON patch + MIDI send | Refine patches, mad-libs prompts, local library, hardware read/write |
| **Line 6 POD HD** | `.hbe` patch file | 1,000+ guitar/amp mad-libs phrases, dice randomizer, local library |

More devices can be added to the home screen over time.

## Quick start

```powershell
git clone https://github.com/mylegitches/patchpipe.git
cd patchpipe
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
copy .env.example .env
```

**Launch** (pick one):

```powershell
# Easiest on Windows — double-click run.bat, or:
.\run.bat

# Or from an activated venv (LAN — other devices on your network can connect):
python -m patchpipe.cli --lan

# Local only (this PC only):
python -m patchpipe.cli
```

Patchpipe opens `http://127.0.0.1:8765` in your browser. **Keep the terminal window open** while you use it.

> If `patchpipe` is not recognized, use `python -m patchpipe.cli` instead — the `patchpipe` script may not be on your PATH.

1. **Home** — click a device card (JUNO-DS or POD HD)
2. **Workspace** — roll a random prompt or write your own
3. **Generate** — model returns a validated patch; results save to `.patchmaker/`

For JUNO-DS MIDI features:

```powershell
pip install -e ".[midi]"
```

## Configuration

Settings are saved to `.env` in the directory where you launch Patchpipe. The UI never sends your API key back to the browser after it is saved.

Shared keys:

- `PATCHPIPE_LLM_BASE_URL` — any OpenAI-compatible endpoint
- `PATCHPIPE_LLM_API_KEY`
- `PATCHPIPE_LLM_MODEL`
- `PATCHPIPE_OUTPUT_DIR` — POD HD `.hbe` output folder

## Project layout

```
src/patchpipe/
  hub/                 # device picker home screen
  server.py            # unified local HTTP server
  devices/
    juno_ds/           # Roland JUNO-DS backend + UI
    pod_hd/            # Line 6 POD HD backend + UI
data/pod_hd/           # POD HD decoder tables + prompt bank
patches/               # POD HD template .hbe files
```

## License

Not yet chosen.
