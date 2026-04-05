from __future__ import annotations

from pathlib import Path

from arelab.agents import merge_candidates, model_candidates
from arelab.analyze import analyze_manifest
from arelab.basement import prepare_basement
from arelab.config import Settings
from arelab.decompile_refine import refine_pseudocode
from arelab.demo import build_demo_inputs
from arelab.ghidra import GhidraAnalyzer
from arelab.ingest import build_manifest
from arelab.intake import infer_input_session
from arelab.locks import workflow_lock
from arelab.model_gateway import ModelGateway
from arelab.report import write_report
from arelab.runner import ToolRunner
from arelab.schemas import RunMetadata, SwapCandidate
from arelab.store import ArtifactStore
from arelab.tooling import detect_tools
from arelab.util import json_dump
from arelab.workflows import load_workflow


def _checkpoint(run_dir: Path, stage: str, payload: dict[str, object]) -> None:
    json_dump(run_dir / "checkpoints" / f"{stage}.json", payload)


def run_pipeline(
    *,
    repo_root: Path,
    input_path: Path | None,
    output_root: Path | None,
    profile: str,
    workflow: str = "default",
    demo: bool = False,
) -> tuple[str, Path]:
    settings = Settings.load(repo_root, workflow=workflow)
    workflow_spec = load_workflow(repo_root, workflow)
    if profile == "auto":
        profile = workflow_spec.pipeline.get("default_profile", "overnight")
    if output_root:
        settings.runs_root = output_root
    store = ArtifactStore(settings.runs_root)
    initial_input = input_path or repo_root
    run_id, run_dir = store.create_run(initial_input, profile, workflow)
    metadata = store.load_metadata(run_dir)
    runner = ToolRunner(run_dir / "logs")
    tools = detect_tools(settings)

    try:
        with workflow_lock(workflow, "pipeline"):
            if demo:
                metadata.stage = "build-demo"
                store.write_metadata(run_dir, metadata)
                actual_input = build_demo_inputs(repo_root, run_dir / "work", runner, tools)
                metadata.input_path = str(actual_input)
                _checkpoint(run_dir, "build-demo", {"input_path": str(actual_input)})
            else:
                if input_path is None:
                    raise ValueError("input_path is required when demo=False")
                actual_input = input_path

            intake_session = infer_input_session(repo_root, actual_input, demo=demo)
            prepare_basement(run_dir, workflow, intake_session)
            metadata.intake_session_id = intake_session.session_id
            metadata.source_type = intake_session.source_type
            json_dump(run_dir / "artifacts" / "tool-detection.json", tools)
            _checkpoint(run_dir, "workflow", {"name": workflow_spec.name, "mode": workflow_spec.mode})

            metadata.stage = "ingest"
            store.write_metadata(run_dir, metadata)
            manifest = build_manifest(actual_input, run_dir / "work", tools, runner)
            json_dump(run_dir / "artifacts" / "manifest.json", manifest.model_dump(mode="json"))
            _checkpoint(run_dir, "ingest", {"artifact_count": len(manifest.nodes)})

            metadata.stage = "analyze"
            store.write_metadata(run_dir, metadata)
            ghidra = GhidraAnalyzer(tools.get("analyzeHeadless"), repo_root, runner)
            analyses = analyze_manifest(manifest, run_dir / "artifacts", tools, runner, ghidra)
            _checkpoint(run_dir, "analyze", {"binary_count": len(analyses)})

            heuristic_only = [SwapCandidate.model_validate(item) for analysis in analyses for item in analysis.heuristics]
            metadata.stage = "reason"
            store.write_metadata(run_dir, metadata)
            llm: list[SwapCandidate] = []
            if profile != "fast":
                if workflow_spec.mode == "parallel":
                    llm = _run_legion_reasoning(
                        settings=settings,
                        run_dir=run_dir,
                        analyses=analyses,
                        heuristic_only=heuristic_only,
                        metadata=metadata,
                        store=store,
                        refine_limit=workflow_spec.pipeline.get("refine_limit", 6),
                    )
                else:
                    llm = _run_agency_reasoning(
                        settings=settings,
                        run_dir=run_dir,
                        analyses=analyses,
                        heuristic_only=heuristic_only,
                        metadata=metadata,
                        store=store,
                        refine_limit=workflow_spec.pipeline.get("refine_limit", 4),
                    )
            merged = merge_candidates(heuristic_only + llm)
            _checkpoint(run_dir, "reason", {"workflow": workflow_spec.name, "swap_count": len(merged)})

            metadata.stage = "report"
            store.write_metadata(run_dir, metadata)
            write_report(run_id, run_dir / "reports", manifest, analyses, merged)
            metadata.stage = "completed"
            metadata.status = "completed"
            metadata.report_path = str(run_dir / "reports" / "report.md")
            store.write_metadata(run_dir, metadata)
            return run_id, run_dir
    except Exception as exc:
        metadata.stage = "failed"
        metadata.status = "failed"
        metadata.error = str(exc)
        store.write_metadata(run_dir, metadata)
        raise


def _refine_shortlist(*, gateway: ModelGateway, analyses, heuristic_only: list[SwapCandidate], limit: int) -> int:
    shortlist = {(candidate.evidence.binary, candidate.evidence.function) for candidate in heuristic_only}
    refined_count = 0
    for analysis in analyses:
        for function in analysis.functions:
            if refined_count >= limit:
                return refined_count
            if (analysis.binary, function.name) not in shortlist:
                continue
            if not function.pseudocode:
                continue
            try:
                refined = refine_pseudocode(gateway, function.name, function.pseudocode)
            except Exception:  # noqa: BLE001
                refined = {"cleaned_code": function.pseudocode, "summary": "refine failed"}
            function.notes.append(refined.get("summary", ""))
            function.pseudocode = refined.get("cleaned_code", function.pseudocode)
            refined_count += 1
    return refined_count


def _run_agency_reasoning(
    *,
    settings: Settings,
    run_dir: Path,
    analyses,
    heuristic_only,
    metadata,
    store,
    refine_limit: int,
) -> list[SwapCandidate]:
    gateway = ModelGateway(settings, run_dir / "prompts")
    metadata.stage = "agency_director"
    store.write_metadata(run_dir, metadata)
    director_summary = gateway.chat_json(
        role="planner",
        system_prompt="You are the Agency Director. Return JSON only with plan_summary and shortlist.",
        user_prompt="Summarize the highest-risk binaries and functions for a serial defensive audit.",
        schema_name="agency-director",
        max_tokens=256,
        timeout=120,
    ) or {"plan_summary": "", "shortlist": []}
    _checkpoint(run_dir, "agency_director", director_summary)

    metadata.stage = "decompile_refine"
    store.write_metadata(run_dir, metadata)
    refined_count = _refine_shortlist(
        gateway=gateway,
        analyses=analyses,
        heuristic_only=heuristic_only,
        limit=refine_limit,
    )
    _checkpoint(run_dir, "decompile_refine", {"refined_functions": refined_count})

    metadata.stage = "agency_auditor"
    store.write_metadata(run_dir, metadata)
    llm = model_candidates(gateway, analyses, roles=("deep", "arbiter"))
    _checkpoint(run_dir, "agency_auditor", {"candidates": len(llm)})
    return llm


def _run_legion_reasoning(
    *,
    settings: Settings,
    run_dir: Path,
    analyses,
    heuristic_only,
    metadata,
    store,
    refine_limit: int,
) -> list[SwapCandidate]:
    gateway = ModelGateway(settings, run_dir / "prompts")
    metadata.stage = "legion_dispatch"
    store.write_metadata(run_dir, metadata)
    dispatch = gateway.chat_json(
        role="planner",
        system_prompt="You are the Legion dispatcher. Return JSON only with lanes and focus.",
        user_prompt="Produce a lane focus plan for triage, refinement, audit, and remediation.",
        schema_name="legion-dispatch",
        max_tokens=256,
        timeout=120,
    ) or {"lanes": []}
    _checkpoint(run_dir, "legion_dispatch", dispatch)

    metadata.stage = "decompile_refine"
    store.write_metadata(run_dir, metadata)
    refined_count = _refine_shortlist(
        gateway=gateway,
        analyses=analyses,
        heuristic_only=heuristic_only,
        limit=refine_limit,
    )
    _checkpoint(run_dir, "decompile_refine", {"refined_functions": refined_count})

    metadata.stage = "legion_lanes"
    store.write_metadata(run_dir, metadata)
    llm = model_candidates(gateway, analyses, roles=("triage", "deep", "cleanup", "clerk"))
    _checkpoint(run_dir, "legion_lanes", {"candidates": len(llm)})
    return llm


def status_for_run(
    repo_root: Path,
    run_id: str,
    output_root: Path | None = None,
    workflow: str = "default",
) -> RunMetadata:
    settings = Settings.load(repo_root, workflow=workflow)
    runs_root = output_root or settings.runs_root
    store = ArtifactStore(runs_root)
    return store.load_metadata(runs_root / run_id)
