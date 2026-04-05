from __future__ import annotations

import argparse
import json
from pathlib import Path

from arelab.basement import prepare_basement
from arelab.disclosure import build_disclosure_manifest, build_disclosure_report, write_disclosure_bundle
from arelab.intake import build_intake_session
from arelab.reporting import build_operational_report
from arelab.schemas import BootChainExposure, BootChainMap, TargetProfile
from arelab.targets import fingerprint_boot_environment, load_target_profile_by_id, verify_ab_partitions
from arelab.util import json_dump, utc_now


def _boundary_name(current_signed: bool, next_signed: bool) -> str:
    left = "signed" if current_signed else "unsigned"
    right = "signed" if next_signed else "unsigned"
    return f"{left}_to_{right}"


def _basement_scope(path: Path) -> tuple[Path, str] | None:
    parts = list(path.resolve(strict=False).parts)
    for workflow_name in ("agency", "legion"):
        marker = ("runs", workflow_name)
        for index in range(len(parts) - 2):
            if tuple(parts[index : index + 2]) != marker:
                continue
            if len(parts) <= index + 3:
                continue
            run_dir = Path(*parts[: index + 3])
            return run_dir, workflow_name
    return None


def map_boot_chain(profile: TargetProfile) -> BootChainMap:
    fingerprint = fingerprint_boot_environment(profile)
    ab_verification = verify_ab_partitions(profile)
    operational_report = build_operational_report(profile, fingerprint, ab_verification)
    component_by_name = {component.name: component for component in profile.boot_components}
    stage_map: dict[str, list[str]] = {}
    trust_boundaries: list[dict[str, object]] = []
    exposures: list[BootChainExposure] = []
    scaffolds: list[dict[str, str]] = []

    for component in profile.boot_components:
        stage_map.setdefault(component.stage, []).append(component.name)
        for next_name in component.verifies:
            next_component = component_by_name.get(next_name)
            if next_component is None:
                continue
            trust_boundary = _boundary_name(component.signed, next_component.signed)
            trust_boundaries.append(
                {
                    "from": component.name,
                    "to": next_component.name,
                    "trust_boundary": trust_boundary,
                }
            )
            scaffold = {
                "title": f"{component.name} -> {next_component.name} verification review",
                "impact": f"Assess whether {component.name} constrains {next_component.name} under {trust_boundary}.",
                "repro": "Collect versioned artifacts, hashes, and verifier policy evidence before triage.",
                "remediation": f"Strengthen signing, rollback, and measurement coverage across {component.name} to {next_component.name}.",
            }
            exposures.append(
                BootChainExposure(
                    component=component.name,
                    stage=component.stage,
                    trust_boundary=trust_boundary,
                    exposure=f"{component.name} delegates trust to {next_component.name}",
                    evidence=component.evidence or [f"{component.name}:{component.stage}"],
                    remediation_focus=f"Validate {component.name} hand-off policy for {next_component.name}.",
                    finding_scaffold=scaffold,
                )
            )
            scaffolds.append(scaffold)

    if fingerprint.bootloader_version:
        scaffolds.append(
            {
                "title": "Bootloader fingerprint corroboration",
                "impact": f"Confirm that observed boot artifacts match bootloader version {fingerprint.bootloader_version}.",
                "repro": "Capture boot logs, kernel cmdline, and hardware-register snapshots from the same session.",
                "remediation": "Preserve fingerprint evidence alongside boot-chain artifacts so later triage can detect spoofed or stale signatures.",
            }
        )
    if fingerprint.device_lock_state in {"unlocked", "mixed"} or fingerprint.verified_boot_state in {"yellow", "orange", "red", "mixed"}:
        exposures.append(
            BootChainExposure(
                component="boot_state_fingerprint",
                stage="bootloader",
                trust_boundary="signed_to_signed",
                exposure=(
                    f"Fingerprinting indicates device_lock_state={fingerprint.device_lock_state} "
                    f"and verified_boot_state={fingerprint.verified_boot_state}."
                ),
                evidence=[
                    *(f"{signal.source}:{signal.key}={signal.value}" for signal in fingerprint.evidence[:6]),
                    *fingerprint.heuristics[:3],
                ],
                remediation_focus="Confirm OEM lock, verified boot policy, and bootloader configuration against trusted acquisition evidence.",
                finding_scaffold={
                    "title": "Security-state drift in boot fingerprint",
                    "impact": "Review whether lock-state or verified-boot drift weakens trust in recovered boot artifacts.",
                    "repro": "Collect synchronized boot logs, cmdline snapshots, and register captures from the same boot.",
                    "remediation": "Restore expected bootloader lock and verified boot policy before relying on downstream findings.",
                },
            )
        )

    for issue in ab_verification.issues:
        stage = "slot_verification"
        if issue.partition == "vbmeta":
            stage = "avb"
        elif issue.partition == "recovery":
            stage = "recovery"
        elif issue.partition == "boot":
            stage = "kernel"
        exposure_scaffold = {
            "title": f"A/B partition review: {issue.issue}",
            "impact": issue.rationale,
            "repro": "Inspect both active and inactive slot artifacts together and compare rollback metadata before triage.",
            "remediation": "Repair cross-slot inconsistencies and preserve both slot views in the evidence bundle.",
        }
        exposures.append(
            BootChainExposure(
                component=f"slot_{issue.slot}",
                stage=stage,
                trust_boundary="signed_to_signed",
                exposure=issue.issue,
                evidence=[item for item in [issue.partition, issue.counterpart_slot, issue.rationale] if item],
                remediation_focus="Validate active and inactive slot integrity before treating a single-slot result as authoritative.",
                finding_scaffold=exposure_scaffold,
            )
        )
        scaffolds.append(exposure_scaffold)

    return BootChainMap(
        target_id=profile.target_id,
        created_at=utc_now(),
        stage_map=stage_map,
        trust_boundaries=trust_boundaries,
        fingerprint=fingerprint,
        ab_verification=ab_verification,
        operational_report=operational_report,
        exposures=exposures,
        finding_scaffolds=scaffolds,
    )


def write_bootchain_bundle(output_root: Path, profile: TargetProfile, chain_map: BootChainMap) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    map_path = output_root / "bootchain-map.json"
    exposures_path = output_root / "exposures.json"
    report_path = output_root / "operational-report.json"
    json_dump(map_path, chain_map.model_dump(mode="json"))
    json_dump(exposures_path, [item.model_dump(mode="json") for item in chain_map.exposures])
    if chain_map.operational_report is not None:
        json_dump(report_path, chain_map.operational_report.model_dump(mode="json"))
    return {
        "bootchain_map": str(map_path),
        "exposures": str(exposures_path),
        "operational_report": str(report_path),
    }


def main_map_bootchain() -> int:
    parser = argparse.ArgumentParser(description="Map boot-chain stages, trust boundaries, and research scaffolds.")
    parser.add_argument("--config", action="append", default=[])
    parser.add_argument("--config-dir", default=None)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--output", default=None)
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()

    profile = load_target_profile_by_id(
        args.target_id,
        [Path(value) for value in args.config],
        Path(args.config_dir) if args.config_dir else None,
    )
    chain_map = map_boot_chain(profile)
    payload: dict[str, object] = {"bootchain_map": chain_map.model_dump(mode="json")}

    if args.output_root:
        output_root = Path(args.output_root)
        payload["written"] = write_bootchain_bundle(output_root, profile, chain_map)
        manifest = build_disclosure_manifest(profile, chain_map)
        report = build_disclosure_report(profile, chain_map, manifest)
        scope = _basement_scope(output_root)
        if scope is not None:
            run_dir, workflow = scope
            session = build_intake_session(
                run_dir.parents[2],
                source_type="reference_file_set",
                reference_paths="\n".join(item.path_hint or item.name for item in profile.artifacts),
                acquisition_notes="boot-chain mapping scaffold generated from authorized target config",
            )
            payload["basement"] = prepare_basement(
                run_dir,
                workflow,
                session,
                target_profile=profile,
                bootchain_map=chain_map,
                disclosure_manifest=manifest,
                disclosure_report=report,
            )
        else:
            payload["disclosure"] = write_disclosure_bundle(output_root / "disclosure", profile, chain_map)

    if args.output:
        json_dump(Path(args.output), payload)
    else:
        print(json.dumps(payload, indent=2))
    return 0
