from __future__ import annotations

import json
from pathlib import Path

from arelab.schemas import ArtifactManifest, BinaryAnalysis, SwapCandidate, SwapReport
from arelab.util import json_dump, utc_now


def write_report(
    run_id: str,
    reports_dir: Path,
    manifest: ArtifactManifest,
    analyses: list[BinaryAnalysis],
    candidates: list[SwapCandidate],
) -> SwapReport:
    summary = {
        "artifact_count": len(manifest.nodes),
        "binary_count": len(analyses),
        "swap_count": len(candidates),
    }
    report = SwapReport(
        run_id=run_id,
        generated_at=utc_now(),
        summary=summary,
        swap_candidates=candidates,
        artifacts=manifest,
        analyses=analyses,
    )
    json_dump(reports_dir / "report.json", json.loads(report.model_dump_json(by_alias=True)))
    lines = [
        f"# Android AutoRELab Report: {run_id}",
        "",
        "## Summary",
        f"- Artifacts discovered: {summary['artifact_count']}",
        f"- Binary analyses: {summary['binary_count']}",
        f"- SWAP candidates: {summary['swap_count']}",
        "",
        "## Top SWAPs",
    ]
    for item in candidates:
        lines.extend(
            [
                f"### {item.id}: {item.title}",
                f"- Class: {item.class_name}",
                f"- Impact: {item.impact}",
                f"- Confidence: {item.confidence:.2f}",
                f"- Location: `{item.evidence.binary}` :: `{item.evidence.function}` @ `{item.evidence.address}`",
                f"- Reachability: {item.reachability}",
                f"- Evidence: {item.evidence.decompile_excerpt}",
                f"- CFG summary: {item.evidence.cfg_summary}",
                f"- Remediation intent: {item.remediation_intent}",
                f"- Verification tests: {item.verification_tests}",
                "",
            ]
        )
    lines.extend(
        [
            "## Appendix",
            "- Tool logs: `logs/`",
            "- Prompt logs: `prompts/`",
            "- Artifact JSON: `artifacts/`",
            "",
        ]
    )
    (reports_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")
    return report
