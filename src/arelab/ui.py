from __future__ import annotations

import json
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arelab.basement import prepare_basement
from arelab.config import Settings
from arelab.intake import IntakeSessionStore, build_intake_session, session_anchor_path
from arelab.model_gateway import ModelGateway
from arelab.pipeline import execute_prepared_run, prepare_run
from arelab.store import ArtifactStore
from arelab.util import tail_text
from arelab.workflows import load_workflow


def create_app(repo_root: Path, workflow: str = "default") -> FastAPI:
    settings = Settings.load(repo_root, workflow=workflow)
    app = FastAPI(title="android-autorelab")
    templates = Jinja2Templates(directory=str(repo_root / "templates"))
    app.mount("/static", StaticFiles(directory=str(repo_root / "static")), name="static")
    workflow_labels = {
        "default": "Shared view",
        "agency": "The Agency",
        "legion": "The Legion",
    }
    stage_help = {
        "created": "Run folder created and ready for analysis.",
        "intake": "Intake material was converted into a run anchor.",
        "intake_bound": "Intake was reviewed and bound to a workflow.",
        "build-demo": "Demo input bundle is being prepared.",
        "ingest": "Source material is being cataloged into artifacts.",
        "analyze": "Artifacts are being analyzed and decompiled.",
        "reason": "The system is reviewing findings and drafting conclusions.",
        "report": "Evidence is being assembled into the final dossier.",
        "completed": "The report and run outputs are ready to review.",
        "failed": "The run stopped before completion and needs review.",
    }
    workflow_help = {
        "agency": {
            "label": "The Agency",
            "summary": "One deliberate path for careful, sequential review.",
            "best_for": "Smaller or high-confidence targets where you want one clear analysis lane.",
            "outputs": "Writes only to runs/agency/...",
        },
        "legion": {
            "label": "The Legion",
            "summary": "Parallel analysis lanes with the same evidence boundaries.",
            "best_for": "Large or noisy targets where comparison and wider triage help.",
            "outputs": "Writes only to runs/legion/...",
        },
    }

    def humanize(value: str | None) -> str:
        if not value:
            return "Unknown"
        return value.replace("_", " ").replace("-", " ").strip().title()

    def describe_run(payload: dict[str, object]) -> dict[str, object]:
        workflow_name = str(payload.get("workflow", "default"))
        stage = str(payload.get("stage", "created"))
        status = str(payload.get("status", "queued"))
        source_type = str(payload.get("source_type") or "unknown")
        output_root = str(payload.get("output_root", ""))
        run_id = str(payload.get("run_id", ""))
        payload["workflow_label"] = workflow_labels.get(workflow_name, humanize(workflow_name))
        payload["status_label"] = humanize(status)
        payload["stage_label"] = humanize(stage)
        payload["stage_help"] = stage_help.get(stage, "Run state recorded.")
        payload["source_label"] = humanize(source_type)
        payload["output_label"] = output_root.replace(str(repo_root) + "\\", "").replace(str(repo_root) + "/", "")
        payload["detail_path"] = f"/runs/{workflow_name}/{run_id}"
        return payload

    def workflow_roots(selected_workflow: str | None = None) -> list[tuple[str, Path]]:
        names = [selected_workflow] if selected_workflow and selected_workflow != "default" else ["agency", "legion", "default"]
        return [(name, repo_root / "runs" / name) for name in names]

    def run_items(selected_workflow: str | None = None) -> list[dict[str, object]]:
        items = []
        for workflow_name, root in workflow_roots(selected_workflow):
            if not root.exists():
                continue
            for run_dir in root.iterdir():
                meta_path = run_dir / "run.json"
                if not meta_path.exists():
                    continue
                payload = None
                for _ in range(5):
                    try:
                        payload = json.loads(meta_path.read_text(encoding="utf-8"))
                        break
                    except json.JSONDecodeError:
                        time.sleep(0.05)
                if payload is None:
                    continue
                payload.setdefault("workflow", workflow_name)
                items.append(describe_run(payload))
        return sorted(items, key=lambda item: (str(item.get("updated_at", "")), str(item.get("run_id", ""))), reverse=True)

    def run_summary(items: list[dict[str, object]]) -> dict[str, int]:
        return {
            "total": len(items),
            "active": sum(1 for item in items if str(item.get("status")) in {"queued", "running"}),
            "completed": sum(1 for item in items if str(item.get("status")) == "completed"),
            "failed": sum(1 for item in items if str(item.get("status")) == "failed"),
        }

    def resolve_run(workflow_name: str, run_id: str) -> tuple[Path, dict[str, object]]:
        run_dir = repo_root / "runs" / workflow_name / run_id
        meta_path = run_dir / "run.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="run not found")
        payload = None
        for _ in range(5):
            try:
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
                break
            except json.JSONDecodeError:
                time.sleep(0.05)
        if payload is None:
            raise HTTPException(status_code=503, detail="run metadata is being updated")
        payload.setdefault("workflow", workflow_name)
        return run_dir, describe_run(payload)

    def basement_summary(run_dir: Path) -> dict[str, object]:
        root = run_dir / "basement"
        if not root.exists():
            return {}
        summary: dict[str, object] = {"root": str(root)}
        session_path = root / "intake" / "session-context.json"
        if session_path.exists():
            summary["session"] = json.loads(session_path.read_text(encoding="utf-8"))
        index_path = root / "index.json"
        if index_path.exists():
            summary["index"] = json.loads(index_path.read_text(encoding="utf-8"))
            summary["output_items"] = [
                {"label": humanize(key), "path": value}
                for key, value in summary["index"].items()
                if isinstance(value, str)
            ]
        return summary

    def workflow_choice_context(workflow_name: str) -> dict[str, object]:
        settings = Settings.load(repo_root, workflow=workflow_name)
        spec = load_workflow(repo_root, workflow_name)
        profiles = sorted(spec.workflow_config.get("profiles", {}).keys()) if hasattr(spec, "workflow_config") else []
        if not profiles:
            profiles = sorted((settings.workflow_config.get("profiles", {}) or {}).keys())
        if not profiles:
            profiles = [settings.workflow_config.get("pipeline", {}).get("default_profile", "auto")]
        configured_models = list(
            dict.fromkeys(str(model) for model in (settings.workflow_config.get("roles", {}) or {}).values() if model)
        )
        return {
            "profiles": profiles,
            "default_profile": settings.workflow_config.get("pipeline", {}).get("default_profile", profiles[0]),
            "configured_models": configured_models,
            "roles": [
                {
                    "name": role,
                    "selected": model,
                    "models": configured_models,
                }
                for role, model in (settings.workflow_config.get("roles", {}) or {}).items()
            ],
        }

    def latest_live_log(run_dir: Path) -> dict[str, str]:
        logs_dir = run_dir / "logs"
        if not logs_dir.exists():
            return {"label": "", "stdout": "", "stderr": ""}
        stdout_logs = sorted(logs_dir.glob("*.stdout.log"))
        stderr_logs = sorted(logs_dir.glob("*.stderr.log"))
        json_logs = sorted(logs_dir.glob("*.json"))
        label = json_logs[-1].stem if json_logs else ""
        stdout_path = stdout_logs[-1] if stdout_logs else None
        stderr_path = stderr_logs[-1] if stderr_logs else None
        return {
            "label": label,
            "stdout": tail_text(stdout_path, lines=32) if stdout_path else "",
            "stderr": tail_text(stderr_path, lines=24) if stderr_path else "",
        }

    def console_history(run_dir: Path) -> list[dict[str, object]]:
        path = run_dir / "prompts" / "operator-console.jsonl"
        if not path.exists():
            return []
        items: list[dict[str, object]] = []
        for line in path.read_text(encoding="utf-8").splitlines()[-10:]:
            if not line.strip():
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return items

    def live_payload(workflow_name: str, run_id: str) -> dict[str, object]:
        run_dir, metadata = resolve_run(workflow_name, run_id)
        checkpoints = sorted(path.name for path in (run_dir / "checkpoints").glob("*.json"))
        report_path = run_dir / "reports" / "report.md"
        return {
            "run": metadata,
            "checkpoints": checkpoints,
            "latest_log": latest_live_log(run_dir),
            "console_history": console_history(run_dir),
            "report_excerpt": tail_text(report_path, lines=40) if report_path.exists() else "",
        }

    @app.get("/", response_class=HTMLResponse)
    async def splash(request: Request) -> HTMLResponse:
        items = run_items(None if workflow == "default" else workflow)
        return templates.TemplateResponse(
            name="intake.html",
            request=request,
            context={
                "title": "Start A Run",
                "workflow": workflow,
                "nav_path": "startup",
                "tracked_runs": len(items),
                "summary": run_summary(items),
                "recent_runs": items[:3],
                "reference_examples": [
                    "downloaded firmware files from SamFW",
                    "vendor firmware packages",
                    "extracted images",
                    "prior evidence bundles",
                    "normalized metadata bundles",
                ],
            },
        )

    @app.get("/runs", response_class=HTMLResponse)
    async def runs(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            name="runs.html",
            request=request,
            context={
                "runs": run_items(None if workflow == "default" else workflow),
                "title": "Runs",
                "workflow": workflow,
                "nav_path": "runs",
                "summary": run_summary(run_items(None if workflow == "default" else workflow)),
            },
        )

    @app.get("/intake/create", response_class=HTMLResponse)
    async def create_intake(
        request: Request,
        source_type: str,
        device_label: str = "",
        connection_hint: str = "",
        project_path: str = "",
        reference_paths: str = "",
        acquisition_notes: str = "",
    ) -> HTMLResponse:
        if source_type not in {"physical_target_device", "saved_project", "reference_file_set"}:
            raise HTTPException(status_code=400, detail="unsupported source_type")
        session = build_intake_session(
            repo_root,
            source_type=source_type,
            device_label=device_label,
            connection_hint=connection_hint,
            project_path=project_path,
            reference_paths=reference_paths,
            acquisition_notes=acquisition_notes,
        )
        IntakeSessionStore(repo_root).save(session)
        return templates.TemplateResponse(
            name="workflow_choice.html",
            request=request,
            context={
                "session": session,
                "title": "Choose A Workflow",
                "workflow": workflow,
                "nav_path": "startup",
                "next_steps": [
                    "Review what the system captured from your input.",
                    "Pick the workflow that fits the pace and depth you want.",
                    "The run will be created only inside the workflow you choose.",
                ],
                "workflow_options": [
                    {
                        "name": "agency",
                        "label": workflow_help["agency"]["label"],
                        "description": workflow_help["agency"]["summary"],
                        "best_for": workflow_help["agency"]["best_for"],
                        "outputs": workflow_help["agency"]["outputs"],
                        "selector": workflow_choice_context("agency"),
                    },
                    {
                        "name": "legion",
                        "label": workflow_help["legion"]["label"],
                        "description": workflow_help["legion"]["summary"],
                        "best_for": workflow_help["legion"]["best_for"],
                        "outputs": workflow_help["legion"]["outputs"],
                        "selector": workflow_choice_context("legion"),
                    },
                ],
            },
        )

    @app.get("/intake/{session_id}", response_class=HTMLResponse)
    async def workflow_choice(request: Request, session_id: str) -> HTMLResponse:
        session = IntakeSessionStore(repo_root).load(session_id)
        return templates.TemplateResponse(
            name="workflow_choice.html",
            request=request,
            context={
                "session": session,
                "title": "Choose A Workflow",
                "workflow": workflow,
                "nav_path": "startup",
                "next_steps": [
                    "Review what the system captured from your input.",
                    "Pick the workflow that fits the pace and depth you want.",
                    "The run will be created only inside the workflow you choose.",
                ],
                "workflow_options": [
                    {
                        "name": "agency",
                        "label": workflow_help["agency"]["label"],
                        "description": workflow_help["agency"]["summary"],
                        "best_for": workflow_help["agency"]["best_for"],
                        "outputs": workflow_help["agency"]["outputs"],
                        "selector": workflow_choice_context("agency"),
                    },
                    {
                        "name": "legion",
                        "label": workflow_help["legion"]["label"],
                        "description": workflow_help["legion"]["summary"],
                        "best_for": workflow_help["legion"]["best_for"],
                        "outputs": workflow_help["legion"]["outputs"],
                        "selector": workflow_choice_context("legion"),
                    },
                ],
            },
        )

    @app.get("/start", response_class=HTMLResponse)
    async def start_from_session(
        session_id: str,
        workflow_name: str,
        profile: str = "auto",
        planner_model: str = "",
        triage_model: str = "",
        deep_model: str = "",
        cleanup_model: str = "",
        decompile_refine_model: str = "",
        clerk_model: str = "",
        arbiter_model: str = "",
    ) -> RedirectResponse:
        if workflow_name not in {"agency", "legion"}:
            raise HTTPException(status_code=400, detail="workflow_name must be agency or legion")
        session = IntakeSessionStore(repo_root).load(session_id)
        anchor_path = session_anchor_path(repo_root, session)
        model_overrides = {
            role: value
            for role, value in {
                "planner": planner_model,
                "triage": triage_model,
                "deep": deep_model,
                "cleanup": cleanup_model,
                "decompile_refine": decompile_refine_model,
                "clerk": clerk_model,
                "arbiter": arbiter_model,
            }.items()
            if value
        }
        run_id, run_dir = prepare_run(
            repo_root=repo_root,
            input_path=anchor_path,
            output_root=repo_root / "runs" / workflow_name,
            profile=profile,
            workflow=workflow_name,
            model_overrides=model_overrides,
        )
        store = ArtifactStore(repo_root / "runs" / workflow_name)
        metadata = store.load_metadata(run_dir)
        metadata.intake_session_id = session.session_id
        metadata.source_type = session.source_type
        metadata.stage = "intake_bound"
        store.write_metadata(run_dir, metadata)
        prepare_basement(run_dir, workflow_name, session)

        def _background_run() -> None:
            try:
                execute_prepared_run(
                    repo_root=repo_root,
                    run_dir=run_dir,
                    input_path=anchor_path,
                    profile=profile,
                    workflow=workflow_name,
                    model_overrides=model_overrides,
                    intake_session=session,
                )
            except Exception:
                return

        threading.Thread(target=_background_run, daemon=True).start()
        return RedirectResponse(url=f"/runs/{workflow_name}/{run_id}", status_code=303)

    @app.get("/runs/{workflow_name}/{run_id}", response_class=HTMLResponse)
    async def run_detail_explicit(request: Request, workflow_name: str, run_id: str) -> HTMLResponse:
        run_dir, metadata = resolve_run(workflow_name, run_id)
        report_md = ""
        report_path = run_dir / "reports" / "report.md"
        if report_path.exists():
            report_md = report_path.read_text(encoding="utf-8")
        basement = basement_summary(run_dir)
        return templates.TemplateResponse(
            name="run_detail.html",
            request=request,
            context={
                "run": metadata,
                "report_md": report_md,
                "title": f"Run {run_id}",
                "workflow": workflow,
                "nav_path": "runs",
                "basement": basement,
                "stage_hint": stage_help.get(str(metadata.get("stage", "")), "Run state recorded."),
                "next_actions": [
                    "Open the report if the run is complete.",
                    "Watch the live activity panel while the run is in progress.",
                    "Use the model console to ask questions or record guidance for later model stages.",
                    "Check the Basement outputs if you want the normalized intake and mapping context.",
                    "Use the manifest link when you need raw artifact structure.",
                ],
                "live_state": live_payload(workflow_name, run_id),
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail_current(request: Request, run_id: str) -> HTMLResponse:
        if workflow == "default":
            raise HTTPException(status_code=404, detail="use /runs/<workflow>/<run_id> in the shared ledger")
        return await run_detail_explicit(request, workflow, run_id)

    @app.get("/runs/{workflow_name}/{run_id}/report", response_class=PlainTextResponse)
    async def report_explicit(workflow_name: str, run_id: str) -> PlainTextResponse:
        path = repo_root / "runs" / workflow_name / run_id / "reports" / "report.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="report not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/runs/{run_id}/report", response_class=PlainTextResponse)
    async def report(run_id: str) -> PlainTextResponse:
        if workflow == "default":
            raise HTTPException(status_code=404, detail="use /runs/<workflow>/<run_id>/report in the shared ledger")
        path = settings.runs_root / run_id / "reports" / "report.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="report not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/runs/{workflow_name}/{run_id}/artifacts", response_class=PlainTextResponse)
    async def artifacts_explicit(workflow_name: str, run_id: str) -> PlainTextResponse:
        path = repo_root / "runs" / workflow_name / run_id / "artifacts" / "manifest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="manifest not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/runs/{run_id}/artifacts", response_class=PlainTextResponse)
    async def artifacts(run_id: str) -> PlainTextResponse:
        if workflow == "default":
            raise HTTPException(status_code=404, detail="use /runs/<workflow>/<run_id>/artifacts in the shared ledger")
        path = settings.runs_root / run_id / "artifacts" / "manifest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="manifest not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/api/runs/{workflow_name}/{run_id}/live", response_class=JSONResponse)
    async def run_live(workflow_name: str, run_id: str) -> JSONResponse:
        return JSONResponse(live_payload(workflow_name, run_id))

    @app.get("/api/runs/{workflow_name}/{run_id}/models", response_class=JSONResponse)
    async def run_models(workflow_name: str, run_id: str) -> JSONResponse:
        run_dir, metadata = resolve_run(workflow_name, run_id)
        run_settings = Settings.load(repo_root, workflow=workflow_name)
        for role, model in metadata.get("model_overrides", {}).items():
            run_settings.model_pins[str(role)] = str(model)
        gateway = ModelGateway(run_settings, run_dir / "prompts")
        configured = list(dict.fromkeys([
            *metadata.get("model_overrides", {}).values(),
            *run_settings.workflow_config.get("roles", {}).values(),
        ]))
        return JSONResponse(
            {
                "available_models": gateway.available_models(),
                "configured_models": configured,
                "selected_models": metadata.get("model_overrides", {}),
            }
        )

    @app.get("/api/workflows/{workflow_name}/models", response_class=JSONResponse)
    async def workflow_models(workflow_name: str) -> JSONResponse:
        if workflow_name not in {"agency", "legion"}:
            raise HTTPException(status_code=400, detail="workflow_name must be agency or legion")
        run_settings = Settings.load(repo_root, workflow=workflow_name)
        gateway = ModelGateway(run_settings, repo_root / ".state" / "ui" / workflow_name)
        configured = list(
            dict.fromkeys(str(model) for model in (run_settings.workflow_config.get("roles", {}) or {}).values() if model)
        )
        try:
            available = gateway.available_models()
            message = "Available models loaded from the workflow router."
            backend_ready = True
        except Exception as exc:  # noqa: BLE001
            available = []
            message = f"Model list is not available yet: {exc}"
            backend_ready = False
        return JSONResponse(
            {
                "workflow": workflow_name,
                "available_models": available,
                "configured_models": configured,
                "backend_ready": backend_ready,
                "message": message,
            }
        )

    @app.post("/api/runs/{workflow_name}/{run_id}/console", response_class=JSONResponse)
    async def run_console(workflow_name: str, run_id: str, request: Request) -> JSONResponse:
        run_dir, metadata = resolve_run(workflow_name, run_id)
        payload = await request.json()
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        selected_model = str(payload.get("model", "")).strip() or None
        save_guidance = bool(payload.get("save_guidance", False))
        run_settings = Settings.load(repo_root, workflow=workflow_name)
        for role, model in metadata.get("model_overrides", {}).items():
            run_settings.model_pins[str(role)] = str(model)
        gateway = ModelGateway(run_settings, run_dir / "prompts")
        try:
            response = gateway.chat_text(
                prompt=prompt,
                model=selected_model,
                role="planner",
                save_guidance=save_guidance,
            )
        except Exception as exc:  # noqa: BLE001
            return JSONResponse(
                {
                    "error": str(exc),
                    "message": "The model console could not reach a usable model backend for this run.",
                },
                status_code=503,
            )
        return JSONResponse(response)

    return app
