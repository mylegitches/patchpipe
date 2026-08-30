"""Persistent local history for generated POD HD patches."""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .errors import ValidationError

LIBRARY_SCHEMA_VERSION = 1


def default_library_path() -> Path:
    override = os.environ.get("PATCHMAKER_LIBRARY_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return Path.cwd().joinpath(".patchmaker", "patches", "pod_hd").resolve()


@dataclass(frozen=True, slots=True)
class PatchRecord:
    id: str
    created_at: str
    request: str
    name: str
    template: str
    hbe_path: str
    spec: dict[str, object]
    parent_id: str | None = None

    def summary(self) -> dict[str, object]:
        amp = self.spec.get("amp")
        amp_model = amp.get("model") if isinstance(amp, dict) else None
        return {
            "id": self.id,
            "created_at": self.created_at,
            "name": self.name,
            "request": self.request,
            "template": self.template,
            "hbe_path": self.hbe_path,
            "amp_model": amp_model,
            "parent_id": self.parent_id,
        }

    def to_dict(self) -> dict[str, object]:
        return {
            "library_schema_version": LIBRARY_SCHEMA_VERSION,
            **self.summary(),
            "spec": self.spec,
        }

    @classmethod
    def from_dict(cls, value: object) -> "PatchRecord":
        if not isinstance(value, dict):
            raise ValidationError("patch history record must be an object")
        required = {
            "library_schema_version", "id", "created_at", "request", "name",
            "template", "hbe_path", "amp_model", "parent_id", "spec",
        }
        if set(value) != required:
            raise ValidationError("patch history record has invalid fields")
        if value["library_schema_version"] != LIBRARY_SCHEMA_VERSION:
            raise ValidationError("unsupported patch history schema")
        record_id = _valid_id(value["id"], "id")
        parent = value["parent_id"]
        parent_id = None if parent is None else _valid_id(parent, "parent_id")
        for name in ("created_at", "request", "name", "template", "hbe_path"):
            if not isinstance(value[name], str) or not value[name]:
                raise ValidationError(f"patch history {name} must be a non-empty string")
        if not isinstance(value["spec"], dict):
            raise ValidationError("patch history spec must be an object")
        return cls(
            id=record_id,
            created_at=value["created_at"],
            request=value["request"],
            name=value["name"],
            template=value["template"],
            hbe_path=value["hbe_path"],
            spec=value["spec"],
            parent_id=parent_id,
        )


def _valid_id(value: object, name: str = "record id") -> str:
    if not isinstance(value, str):
        raise ValidationError(f"{name} must be a UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as error:
        raise ValidationError(f"{name} must be a UUID") from error
    if str(parsed) != value.lower():
        raise ValidationError(f"{name} must be a canonical UUID")
    return str(parsed)


class PatchLibrary:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_library_path()).resolve()

    def save(
        self,
        *,
        request: str,
        name: str,
        template: str,
        hbe_path: str,
        spec: dict[str, object],
        parent_id: str | None = None,
    ) -> PatchRecord:
        if parent_id is not None:
            _valid_id(parent_id, "parent_id")
        record = PatchRecord(
            id=str(uuid.uuid4()),
            created_at=datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            request=request,
            name=name,
            template=template,
            hbe_path=hbe_path,
            spec=spec,
            parent_id=parent_id,
        )
        self.root.mkdir(parents=True, exist_ok=True)
        target = self.root.joinpath(f"{record.id}.json")
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=self.root, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(record.to_dict(), handle, indent=2)
            handle.write("\n")
        try:
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return record

    def load(self, record_id: str) -> PatchRecord:
        clean_id = _valid_id(record_id)
        target = self.root.joinpath(f"{clean_id}.json")
        if not target.is_file():
            raise ValidationError("saved patch was not found")
        try:
            return PatchRecord.from_dict(json.loads(target.read_text(encoding="utf-8")))
        except json.JSONDecodeError as error:
            raise ValidationError("saved patch record contains invalid JSON") from error

    def delete(self, record_id: str) -> PatchRecord:
        record = self.load(record_id)
        target = self.root.joinpath(f"{record.id}.json")
        try:
            target.unlink()
        except OSError as error:
            raise ValidationError("saved patch could not be deleted") from error
        return record

    def list(self) -> list[dict[str, object]]:
        if not self.root.is_dir():
            return []
        records: list[PatchRecord] = []
        for path in self.root.glob("*.json"):
            try:
                records.append(PatchRecord.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, json.JSONDecodeError, ValidationError):
                continue
        records.sort(key=lambda record: (record.created_at, record.id), reverse=True)
        return [record.summary() for record in records]
