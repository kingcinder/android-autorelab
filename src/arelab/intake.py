from __future__ import annotations

import json
from pathlib import Path

from arelab.schemas import IntakeReference, IntakeSessionContext
from arelab.util import json_dump, slugify, timestamp_slug, utc_now


def _session_store_root(repo_root: Path) -> Path:
    path = repo_root / ".state" / "intake-sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _session_path(repo_root: Path, session_id: str) -> Path:
    return _session_store_root(repo_root) / f"{session_id}.json"


def _reference_kind(value: str) -> str:
    lowered = value.lower()
    if "samfw" in lowered:
        return "samfw_firmware_bundle"
    if "evidence" in lowered:
        return "prior_evidence_bundle"
    if "metadata" in lowered:
        return "normalized_metadata_bundle"
    if lowered.endswith((".zip", ".7z", ".tar", ".md5")):
        return "vendor_firmware_package"
    if lowered.endswith((".img", ".bin", ".elf", ".mbn")):
        return "extracted_image"
    if lowered.endswith((".json", ".yaml", ".yml")):
        return "metadata_bundle"
    return "reference_bundle"


def _split_reference_values(raw_value: str) -> list[str]:
    values: list[str] = []
    for chunk in raw_value.replace(";", "\n").splitlines():
        candidate = chunk.strip().strip('"').strip("'")
        if candidate:
            values.append(candidate)
    return values


def _canonical_anchor(raw_value: str, fallback: str) -> str:
    return slugify(raw_value or fallback)


def _normalize_reference_paths(raw_value: str) -> list[IntakeReference]:
    references: list[IntakeReference] = []
    for value in _split_reference_values(raw_value):
        candidate = Path(value).expanduser()
        references.append(
            IntakeReference(
                raw_value=value,
                resolved_path=str(candidate.resolve(strict=False)),
                exists=candidate.exists(),
                inferred_kind=_reference_kind(value),
            )
        )
    return references


def build_intake_session(
    repo_root: Path,
    *,
    source_type: str,
    device_label: str = "",
    connection_hint: str = "",
    project_path: str = "",
    reference_paths: str = "",
    acquisition_notes: str = "",
) -> IntakeSessionContext:
    session_id = timestamp_slug()
    provenance_notes = [line.strip() for line in acquisition_notes.splitlines() if line.strip()]
    provided: dict[str, object] = {}
    inferred: dict[str, object] = {}
    unknown: list[str] = []
    references: list[IntakeReference] = []

    if source_type == "physical_target_device":
        provided = {
            "device_label": device_label.strip(),
            "connection_hint": connection_hint.strip(),
            "acquisition_notes": provenance_notes,
        }
        inferred = {
            "source_label": device_label.strip() or "physical-target-device",
            "context_mode": "live_acquisition",
            "provenance_scope": "authorized_lab_capture",
        }
        unknown = [
            "build identifier remains unknown until acquisition completes",
            "artifact completeness remains unknown until a capture bundle is produced",
        ]
    elif source_type == "saved_project":
        project = Path(project_path.strip()).expanduser()
        provided = {
            "project_path": str(project.resolve(strict=False)),
            "acquisition_notes": provenance_notes,
        }
        inferred = {
            "source_label": project.name or "saved-project",
            "project_exists": project.exists(),
            "context_mode": "saved_project_resume",
        }
        if not project.exists():
            unknown.append("saved project path does not exist yet on disk")
        unknown.append("original device acquisition provenance remains unknown unless the project bundle documents it")
    else:
        references = _normalize_reference_paths(reference_paths)
        provided = {
            "reference_paths": [item.resolved_path for item in references],
            "acquisition_notes": provenance_notes,
        }
        inferred = {
            "source_label": references[0].raw_value if references else "reference-file-set",
            "reference_count": len(references),
            "detected_reference_kinds": sorted({item.inferred_kind for item in references}),
            "context_mode": "reference_material_import",
        }
        if not references:
            unknown.append("no reference file or file set was provided")
        if any(not item.exists for item in references):
            unknown.append("one or more reference paths do not exist yet on disk")

    anchor_value = str(
        provided.get("project_path")
        or inferred.get("source_label")
        or f"{source_type}-{session_id}"
    )
    canonical_keys = {
        "session_key": f"session-{_canonical_anchor(anchor_value, session_id)}",
        "device_key": f"device-{_canonical_anchor(str(provided.get('device_label', 'target')), 'target')}",
        "build_key": f"build-{_canonical_anchor(str(provided.get('project_path', inferred.get('source_label', 'unknown-build'))), 'unknown-build')}",
        "artifact_key": f"artifact-{_canonical_anchor(anchor_value, 'artifact-set')}",
    }

    return IntakeSessionContext(
        session_id=session_id,
        created_at=utc_now(),
        source_type=source_type,
        provided=provided,
        inferred=inferred,
        unknown=unknown,
        provenance_notes=provenance_notes,
        references=references,
        canonical_keys=canonical_keys,
    )


def infer_input_session(repo_root: Path, input_path: Path, *, demo: bool = False) -> IntakeSessionContext:
    notes = ["demo-generated input bundle"] if demo else ["repo-local intake inferred from direct CLI run"]
    session = build_intake_session(
        repo_root,
        source_type="reference_file_set",
        reference_paths=str(input_path.resolve(strict=False)),
        acquisition_notes="\n".join(notes),
    )
    session.inferred["anchor_input_path"] = str(input_path.resolve(strict=False))
    return session


def session_anchor_path(repo_root: Path, session: IntakeSessionContext) -> Path:
    project_path = session.provided.get("project_path")
    if isinstance(project_path, str) and project_path:
        return Path(project_path)
    if session.references:
        return Path(session.references[0].resolved_path)
    return repo_root / f"intake-{session.session_id}"


class IntakeSessionStore:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root

    def save(self, session: IntakeSessionContext) -> Path:
        path = _session_path(self.repo_root, session.session_id)
        json_dump(path, session.model_dump(mode="json"))
        return path

    def load(self, session_id: str) -> IntakeSessionContext:
        path = _session_path(self.repo_root, session_id)
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return IntakeSessionContext.model_validate(payload)
