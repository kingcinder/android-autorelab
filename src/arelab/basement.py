from __future__ import annotations

from pathlib import Path

from arelab.schemas import BootChainMap, DisclosureManifest, IntakeSessionContext, TargetProfile
from arelab.util import json_dump, utc_now


def basement_root(run_dir: Path) -> Path:
    path = run_dir / "basement"
    path.mkdir(parents=True, exist_ok=True)
    return path


def prepare_basement(
    run_dir: Path,
    workflow: str,
    session: IntakeSessionContext,
    *,
    target_profile: TargetProfile | None = None,
    bootchain_map: BootChainMap | None = None,
    disclosure_manifest: DisclosureManifest | None = None,
    disclosure_report: str | None = None,
) -> dict[str, str]:
    root = basement_root(run_dir)
    intake_dir = root / "intake"
    evidence_dir = root / "evidence"
    validation_dir = root / "validation"
    repro_dir = root / "reproducibility"
    for path in (intake_dir, evidence_dir, validation_dir, repro_dir):
        path.mkdir(parents=True, exist_ok=True)

    session_path = intake_dir / "session-context.json"
    json_dump(session_path, session.model_dump(mode="json"))
    provenance_path = intake_dir / "provenance.json"
    json_dump(
        provenance_path,
        {
            "workflow": workflow,
            "recorded_at": utc_now(),
            "provided": session.provided,
            "inferred": session.inferred,
            "unknown": session.unknown,
            "provenance_notes": session.provenance_notes,
        },
    )
    evidence_path = evidence_dir / "organization.json"
    json_dump(
        evidence_path,
        {
            "workflow": workflow,
            "source_type": session.source_type,
            "canonical_keys": session.canonical_keys,
            "references": [item.model_dump(mode="json") for item in session.references],
        },
    )
    validation_path = validation_dir / "readiness.json"
    json_dump(
        validation_path,
        {
            "workflow": workflow,
            "ready_for_binding": True,
            "unknown_items": session.unknown,
            "notes": "Basement remains workflow-scoped and writes only under this run directory.",
        },
    )
    repro_path = repro_dir / "scaffold.json"
    json_dump(
        repro_path,
        {
            "workflow": workflow,
            "recorded_at": utc_now(),
            "steps": [
                "Preserve the original intake material or device notes.",
                "Capture normalized metadata before deeper reversing or mapping.",
                "Store all Basement outputs under runs/<workflow>/basement/ only.",
            ],
        },
    )

    index: dict[str, str] = {
        "session_context": str(session_path),
        "provenance": str(provenance_path),
        "evidence_organization": str(evidence_path),
        "validation": str(validation_path),
        "reproducibility": str(repro_path),
    }

    if target_profile is not None:
        normalization_dir = root / "normalization"
        normalization_dir.mkdir(parents=True, exist_ok=True)
        target_path = normalization_dir / "target-profile.json"
        json_dump(target_path, target_profile.model_dump(mode="json"))
        index["target_profile"] = str(target_path)

    if bootchain_map is not None:
        mapping_dir = root / "mapping"
        mapping_dir.mkdir(parents=True, exist_ok=True)
        map_path = mapping_dir / "bootchain-map.json"
        exposures_path = mapping_dir / "exposures.json"
        json_dump(map_path, bootchain_map.model_dump(mode="json"))
        json_dump(exposures_path, [item.model_dump(mode="json") for item in bootchain_map.exposures])
        index["bootchain_map"] = str(map_path)
        index["exposures"] = str(exposures_path)

    if disclosure_manifest is not None:
        disclosure_dir = root / "disclosure"
        disclosure_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = disclosure_dir / "evidence-manifest.json"
        json_dump(manifest_path, disclosure_manifest.model_dump(mode="json"))
        index["disclosure_manifest"] = str(manifest_path)
        if disclosure_report is not None:
            report_path = disclosure_dir / "disclosure-report.md"
            report_path.write_text(disclosure_report, encoding="utf-8")
            index["disclosure_report"] = str(report_path)

    index_path = root / "index.json"
    json_dump(index_path, index)
    index["index"] = str(index_path)
    return index
