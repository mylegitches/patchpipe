"""GUI service layer for the JUNO-DS patch maker."""

from __future__ import annotations

import os
import sys
from dataclasses import asdict
from typing import Callable, Mapping

from .client import JunoClient
from .configuration import read_local_env, update_local_env
from .designer import SoundDesigner
from .errors import PatchValidationError
from .mido_transport import MidoTransport, port_names
from .model import JunoPatch
from .openai_compatible import OpenAICompatiblePlanner
from .patch_library import PatchLibrary
from .prompt_randomizer import SYNTH_SOUND_ATTRIBUTES, randomize_prompt, resolve_sound_language


def demo_patch() -> JunoPatch:
    return JunoPatch.initialized(name="INIT PATCH", category=29).with_common_parameters(level=100)


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PatchValidationError(f"{name} must be a non-empty string")
    return value.strip()


def _device_id(value: object) -> int:
    if value is None:
        return 0x10
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 0x1F:
        raise PatchValidationError("device_id must be an integer between 0 and 31")
    return value


def _configuration_value(name: str) -> str | None:
    from patchpipe.configuration import read_llm_value

    aliases = {
        "PATCHMAKER_LLM_BASE_URL": ("PATCHPIPE_LLM_BASE_URL", "PATCHMAKER_LLM_BASE_URL", "AI_BASE_URL"),
        "PATCHMAKER_LLM_MODEL": ("PATCHPIPE_LLM_MODEL", "PATCHMAKER_LLM_MODEL", "AI_MODEL"),
        "PATCHMAKER_LLM_API_KEY": ("PATCHPIPE_LLM_API_KEY", "PATCHMAKER_LLM_API_KEY", "AI_API_KEY"),
    }
    return read_llm_value(*aliases.get(name, (name,)))


class GuiService:
    def __init__(
        self,
        *,
        planner_factory: Callable[..., object] = OpenAICompatiblePlanner,
        ports_provider: Callable[[], tuple[list[str], list[str]]] = port_names,
        transport_factory: Callable[[str, str], object] = MidoTransport,
        library: PatchLibrary | None = None,
    ) -> None:
        self.planner_factory = planner_factory
        self.ports_provider = ports_provider
        self.transport_factory = transport_factory
        self.library = library or PatchLibrary()

    def dispatch(self, path: str, payload: object | None = None) -> dict[str, object]:
        data = payload if isinstance(payload, Mapping) else {}
        if path == "/api/demo":
            return {"patch": demo_patch().to_dict()}
        if path == "/api/random-prompt":
            result = randomize_prompt()
            return {
                "prompt": result.prompt,
                "attributes": dict(result.attributes),
                "parameter_mapping": resolve_sound_language(result.prompt),
            }
        if path == "/api/prompt-attributes":
            return {"attributes": {key: list(values) for key, values in SYNTH_SOUND_ATTRIBUTES.items()}}
        if path == "/api/history":
            return {"patches": self.library.list()}
        if path == "/api/history/get":
            record_id = _required_string(data.get("id"), "id")
            record = self.library.load(record_id)
            return {
                "record": record.summary(),
                "patch": record.patch.to_dict(),
                "message": record.explanation,
            }
        if path == "/api/history/delete":
            record_id = _required_string(data.get("id"), "id")
            record = self.library.delete(record_id)
            return {"id": record.id, "message": f"Deleted {record.patch.name} from the library"}
        if path == "/api/configuration":
            return {
                "base_url": _configuration_value("PATCHMAKER_LLM_BASE_URL") or "https://openrouter.ai/api/v1",
                "model": _configuration_value("PATCHMAKER_LLM_MODEL") or "openrouter/free",
                "api_key_configured": bool(_configuration_value("PATCHMAKER_LLM_API_KEY")),
                "storage": ".env",
            }
        if path == "/api/save-configuration":
            from patchpipe.configuration import save_llm_configuration

            base_url = _required_string(data.get("base_url"), "base_url")
            model = _required_string(data.get("model"), "model")
            supplied_key = data.get("api_key")
            if supplied_key is not None and not isinstance(supplied_key, str):
                raise PatchValidationError("api_key must be a string")
            api_key = supplied_key.strip() if isinstance(supplied_key, str) else ""
            if not api_key:
                api_key = _configuration_value("PATCHMAKER_LLM_API_KEY") or ""
            save_llm_configuration(base_url=base_url, model=model, api_key=api_key)
            update_local_env(
                {
                    "PATCHMAKER_LLM_API_KEY": api_key,
                    "PATCHMAKER_LLM_BASE_URL": base_url,
                    "PATCHMAKER_LLM_MODEL": model,
                }
            )
            return {
                "message": "Settings saved locally",
                "api_key_configured": bool(api_key),
                "storage": ".env",
            }
        if path == "/api/test-connection":
            base_url = _required_string(
                data.get("base_url") or _configuration_value("PATCHMAKER_LLM_BASE_URL"), "base_url"
            )
            model = _required_string(
                data.get("model") or _configuration_value("PATCHMAKER_LLM_MODEL"), "model"
            )
            api_key = data.get("api_key") or _configuration_value("PATCHMAKER_LLM_API_KEY")
            if api_key is not None and not isinstance(api_key, str):
                raise PatchValidationError("api_key must be a string")
            planner = self.planner_factory(
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout=30.0,
            )
            resolved_model = planner.test_connection()  # type: ignore[attr-defined]
            return {
                "message": "Connection successful",
                "model": resolved_model,
                "authenticated": bool(api_key),
            }
        if path == "/api/ports":
            inputs, outputs = self.ports_provider()
            return {"inputs": inputs, "outputs": outputs}
        if path == "/api/validate":
            patch = JunoPatch.from_dict(data.get("patch"))
            return {"patch": patch.to_dict(), "message": f"{patch.name} is valid"}
        if path == "/api/refine":
            patch = JunoPatch.from_dict(data.get("patch"))
            request = _required_string(data.get("request"), "request")
            base_url = _required_string(
                data.get("base_url") or _configuration_value("PATCHMAKER_LLM_BASE_URL"), "base_url"
            )
            model = _required_string(
                data.get("model") or _configuration_value("PATCHMAKER_LLM_MODEL"), "model"
            )
            api_key = data.get("api_key") or _configuration_value("PATCHMAKER_LLM_API_KEY")
            if api_key is not None and not isinstance(api_key, str):
                raise PatchValidationError("api_key must be a string")
            planner = self.planner_factory(
                base_url=base_url,
                model=model,
                api_key=api_key,
                timeout=60.0,
            )
            result = SoundDesigner(planner).refine(patch, request)  # type: ignore[arg-type]
            plan = asdict(result.plan)
            parent_value = data.get("parent_id")
            if parent_value is not None and not isinstance(parent_value, str):
                raise PatchValidationError("parent_id must be a string or null")
            record = self.library.save(
                result.patch,
                request=request,
                explanation=result.plan.explanation,
                parent_id=parent_value,
            )
            return {
                "patch": result.patch.to_dict(),
                "plan": plan,
                "message": result.plan.explanation,
                "record": record.summary(),
            }
        if path == "/api/read":
            input_port = _required_string(data.get("input_port"), "input_port")
            output_port = _required_string(data.get("output_port"), "output_port")
            with self.transport_factory(input_port, output_port) as transport:  # type: ignore[attr-defined]
                patch = JunoClient(transport, device_id=_device_id(data.get("device_id"))).read_current_patch()
            return {"patch": patch.to_dict(), "message": f"Read {patch.name} from the JUNO-DS"}
        if path == "/api/write":
            if data.get("confirm") is not True:
                raise PatchValidationError("temporary-buffer write must be explicitly confirmed")
            patch = JunoPatch.from_dict(data.get("patch"))
            input_port = _required_string(data.get("input_port"), "input_port")
            output_port = _required_string(data.get("output_port"), "output_port")
            with self.transport_factory(input_port, output_port) as transport:  # type: ignore[attr-defined]
                JunoClient(transport, device_id=_device_id(data.get("device_id"))).write_temporary_patch(patch)
            return {"message": f"Sent {patch.name} to the temporary edit buffer"}
        raise PatchValidationError(f"unknown API route: {path}")
