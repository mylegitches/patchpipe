"""GUI service layer for the Line 6 POD HD patch maker."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Mapping

from .ai_client import DEFAULT_TEMPLATE, generate_patch_file, test_connection
from .configuration import apply_config_to_process, read_local_env, update_local_env
from .errors import ValidationError
from .patch_library import PatchLibrary
from .paths import PATCHES_DIR
from .prompt_randomizer import GUITAR_SOUND_ATTRIBUTES, randomize_prompt, vocabulary_count


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _configuration_value(name: str) -> str | None:
    from patchpipe.configuration import read_llm_value

    aliases = {
        "AI_BASE_URL": ("PATCHPIPE_LLM_BASE_URL", "AI_BASE_URL"),
        "AI_API_KEY": ("PATCHPIPE_LLM_API_KEY", "AI_API_KEY"),
        "AI_MODEL": ("PATCHPIPE_LLM_MODEL", "AI_MODEL"),
        "OUTPUT_DIR": ("PATCHPIPE_OUTPUT_DIR", "OUTPUT_DIR"),
        "DEFAULT_TEMPLATE": ("DEFAULT_TEMPLATE",),
    }
    if name in aliases:
        return read_llm_value(*aliases[name])
    local = read_local_env().get(name)
    if local:
        return local
    value = os.environ.get(name)
    if value:
        return value
    if sys.platform != "win32":
        return None
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
            stored, _ = winreg.QueryValueEx(key, name)
        return stored if isinstance(stored, str) and stored else None
    except OSError:
        return None


def list_templates() -> list[str]:
    if not PATCHES_DIR.is_dir():
        return [DEFAULT_TEMPLATE]
    return sorted(path.name for path in PATCHES_DIR.glob("*.hbe"))


def default_output_dir() -> Path:
    configured = _configuration_value("OUTPUT_DIR")
    if configured:
        return Path(configured).expanduser().resolve()
    return Path.cwd().joinpath("output").resolve()


class GuiService:
    def __init__(self, library: PatchLibrary | None = None) -> None:
        self.library = library or PatchLibrary()

    def dispatch(self, path: str, payload: object | None = None) -> dict[str, object]:
        data = payload if isinstance(payload, Mapping) else {}
        if path == "/api/random-prompt":
            result = randomize_prompt()
            return {
                "prompt": result.prompt,
                "attributes": dict(result.attributes),
                "vocabulary_count": vocabulary_count(),
            }
        if path == "/api/prompt-attributes":
            return {"attributes": {key: list(values) for key, values in GUITAR_SOUND_ATTRIBUTES.items()}}
        if path == "/api/templates":
            templates = list_templates()
            default = _configuration_value("DEFAULT_TEMPLATE") or DEFAULT_TEMPLATE
            if default not in templates and templates:
                default = templates[0]
            return {"templates": templates, "default": default}
        if path == "/api/history":
            return {"patches": self.library.list()}
        if path == "/api/history/get":
            record_id = _required_string(data.get("id"), "id")
            record = self.library.load(record_id)
            return {"record": record.summary(), "spec": record.spec, "message": f"Loaded {record.name}"}
        if path == "/api/history/delete":
            record_id = _required_string(data.get("id"), "id")
            record = self.library.delete(record_id)
            return {"id": record.id, "message": f"Deleted {record.name} from the library"}
        if path == "/api/configuration":
            output_dir = _configuration_value("OUTPUT_DIR") or str(default_output_dir())
            return {
                "base_url": _configuration_value("AI_BASE_URL") or "https://api.openai.com/v1",
                "model": _configuration_value("AI_MODEL") or "gpt-4o-mini",
                "api_key_configured": bool(_configuration_value("AI_API_KEY")),
                "output_dir": output_dir,
                "default_template": _configuration_value("DEFAULT_TEMPLATE") or DEFAULT_TEMPLATE,
                "storage": ".env",
                "vocabulary_count": vocabulary_count(),
            }
        if path == "/api/save-configuration":
            from patchpipe.configuration import save_llm_configuration

            base_url = _required_string(data.get("base_url"), "base_url")
            model = _required_string(data.get("model"), "model")
            output_dir = _required_string(data.get("output_dir"), "output_dir")
            default_template = _required_string(data.get("default_template"), "default_template")
            supplied_key = data.get("api_key")
            if supplied_key is not None and not isinstance(supplied_key, str):
                raise ValidationError("api_key must be a string")
            api_key = supplied_key.strip() if isinstance(supplied_key, str) else ""
            if not api_key:
                api_key = _configuration_value("AI_API_KEY") or ""
            save_llm_configuration(base_url=base_url, model=model, api_key=api_key, output_dir=output_dir)
            update_local_env(
                {
                    "AI_BASE_URL": base_url,
                    "AI_API_KEY": api_key,
                    "AI_MODEL": model,
                    "OUTPUT_DIR": output_dir,
                    "DEFAULT_TEMPLATE": default_template,
                }
            )
            apply_config_to_process(read_local_env())
            Path(output_dir).expanduser().mkdir(parents=True, exist_ok=True)
            return {
                "message": "Settings saved locally",
                "api_key_configured": bool(api_key),
                "storage": ".env",
            }
        if path == "/api/test-connection":
            base_url = _required_string(
                data.get("base_url") or _configuration_value("AI_BASE_URL"), "base_url"
            )
            model = _required_string(data.get("model") or _configuration_value("AI_MODEL"), "model")
            api_key = data.get("api_key") or _configuration_value("AI_API_KEY")
            if api_key is not None and not isinstance(api_key, str):
                raise ValidationError("api_key must be a string")
            os.environ["AI_BASE_URL"] = base_url
            os.environ["AI_MODEL"] = model
            if api_key:
                os.environ["AI_API_KEY"] = api_key
            resolved_model = test_connection()
            return {
                "message": "Connection successful",
                "model": resolved_model,
                "authenticated": bool(api_key),
            }
        if path == "/api/generate":
            request = _required_string(data.get("request"), "request")
            template = _required_string(
                data.get("template") or _configuration_value("DEFAULT_TEMPLATE") or DEFAULT_TEMPLATE,
                "template",
            )
            output_dir = _required_string(
                data.get("output_dir") or _configuration_value("OUTPUT_DIR") or str(default_output_dir()),
                "output_dir",
            )
            apply_config_to_process(read_local_env())
            os.environ["AI_BASE_URL"] = _required_string(
                data.get("base_url") or _configuration_value("AI_BASE_URL"), "base_url"
            )
            os.environ["AI_MODEL"] = _required_string(
                data.get("model") or _configuration_value("AI_MODEL"), "model"
            )
            api_key = data.get("api_key") or _configuration_value("AI_API_KEY")
            if api_key:
                os.environ["AI_API_KEY"] = api_key
            parent_value = data.get("parent_id")
            if parent_value is not None and not isinstance(parent_value, str):
                raise ValidationError("parent_id must be a string or null")
            try:
                spec, out_path = generate_patch_file(request, template=template, output_dir=output_dir)
            except Exception as error:
                raise ValidationError(f"AI generation failed: {error}") from error
            record = self.library.save(
                request=request,
                name=spec["patch_name"],
                template=template,
                hbe_path=str(out_path),
                spec=spec,
                parent_id=parent_value,
            )
            return {
                "spec": spec,
                "hbe_path": str(out_path),
                "message": f"Generated {spec['patch_name']} and saved to {out_path.name}",
                "record": record.summary(),
            }
        raise ValidationError(f"unknown API route: {path}")
