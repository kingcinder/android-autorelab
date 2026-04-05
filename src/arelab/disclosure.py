from __future__ import annotations

from pathlib import Path

from arelab.schemas import BootChainMap, DisclosureManifest, TargetProfile
from arelab.util import json_dump, utc_now


def build_disclosure_manifest(profile: TargetProfile, chain_map: BootChainMap) -> DisclosureManifest:
    return DisclosureManifest(
        target_id=profile.target_id,
        generated_at=utc_now(),
        chain_of_custody=[
            "Authorized target profile loaded from repo-local config.",
            "Research artifacts normalized before boot-chain mapping.",
            "All resulting disclosure scaffolds remain read-only and evidence-oriented.",
        ],
        artifacts=[
            {
                "name": artifact.name,
                "kind": artifact.kind,
                "provenance": artifact.provenance,
                "path_hint": artifact.path_hint,
            }
            for artifact in profile.artifacts
        ],
        exposures=[item.model_dump(mode="json") for item in chain_map.exposures],
        reproduction_steps=[
            "Preserve source bundle hashes and acquisition notes.",
            "Confirm stage ordering and verifier relationships from extracted evidence.",
            "Re-run boot-chain mapping against the same target profile and compare exposure deltas.",
            "Capture timing traces and hardware/software correlation evidence for any boot anomaly under review.",
        ],
    )


def build_disclosure_report(profile: TargetProfile, chain_map: BootChainMap, manifest: DisclosureManifest) -> str:
    lines = [
        f"# Disclosure Scaffold: {profile.target_id}",
        "",
        "## Scope",
        f"- Vendor: {profile.vendor}",
        f"- Model: {profile.model}",
        f"- Build: {profile.build_id}",
        f"- Authorized scope: {profile.authorized_scope}",
        "",
        "## Impact",
        f"- Boot-chain depth under review: {profile.bootchain_depth}",
        f"- Disclosure value score: {profile.disclosure_value}",
        "",
        "## Evidence",
        *(f"- {artifact['kind']}: {artifact['name']}" for artifact in manifest.artifacts),
        "",
        "## Operational Telemetry",
        *(
            [
                f"- Memory regions captured: {len(chain_map.operational_report.memory_regions)}",
                f"- Timing stages analyzed: {len(chain_map.operational_report.timing_analysis)}",
                f"- Software/hardware correlations: {len(chain_map.operational_report.correlations)}",
                f"- Historical references matched: {len(chain_map.operational_report.reference_matches)}",
                *(f"- Anomaly: {item}" for item in chain_map.operational_report.anomalies),
            ]
            if chain_map.operational_report is not None
            else ["- No telemetry report was generated from the supplied metadata."]
        ),
        "",
        "## Historical References",
        *(
            [
                *(
                    f"- {item.title} ({item.classification}, score={item.score}): "
                    f"{'; '.join(item.rationale) or 'matched by catalog heuristics'}"
                    for item in chain_map.operational_report.reference_matches
                )
            ]
            if chain_map.operational_report is not None and chain_map.operational_report.reference_matches
            else ["- No historical reference catalog matches were emitted for this target."]
        ),
        "",
        "## Reproducibility",
        *(f"- {step}" for step in manifest.reproduction_steps),
        "",
        "## Remediation",
        *(f"- {exposure.remediation_focus}" for exposure in chain_map.exposures),
        *(
            [*(f"- {item.title}: {item.rationale}" for item in chain_map.operational_report.validation_recommendations)]
            if chain_map.operational_report is not None
            else []
        ),
    ]
    return "\n".join(lines).strip() + "\n"


def write_disclosure_bundle(
    output_root: Path,
    profile: TargetProfile,
    chain_map: BootChainMap,
) -> dict[str, str]:
    output_root.mkdir(parents=True, exist_ok=True)
    manifest = build_disclosure_manifest(profile, chain_map)
    report = build_disclosure_report(profile, chain_map, manifest)
    manifest_path = output_root / "evidence-manifest.json"
    report_path = output_root / "disclosure-report.md"
    json_dump(manifest_path, manifest.model_dump(mode="json"))
    report_path.write_text(report, encoding="utf-8")
    return {
        "manifest": str(manifest_path),
        "report": str(report_path),
    }
