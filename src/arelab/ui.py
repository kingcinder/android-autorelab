from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arelab.basement import prepare_basement
from arelab.config import Settings
from arelab.intake import IntakeSessionStore, build_intake_session, session_anchor_path
from arelab.store import ArtifactStore


def create_app(repo_root: Path, workflow: str = "default") -> FastAPI:
    settings = Settings.load(repo_root, workflow=workflow)
    app = FastAPI(title="android-autorelab")
    templates = Jinja2Templates(directory=str(repo_root / "templates"))
    app.mount("/static", StaticFiles(directory=str(repo_root / "static")), name="static")

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
                payload = json.loads(meta_path.read_text(encoding="utf-8"))
                payload.setdefault("workflow", workflow_name)
                items.append(payload)
        return sorted(items, key=lambda item: (str(item.get("updated_at", "")), str(item.get("run_id", ""))), reverse=True)

    def resolve_run(workflow_name: str, run_id: str) -> tuple[Path, dict[str, object]]:
        run_dir = repo_root / "runs" / workflow_name / run_id
        meta_path = run_dir / "run.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="run not found")
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        payload.setdefault("workflow", workflow_name)
        return run_dir, payload

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
        return summary

    @app.get("/", response_class=HTMLResponse)
    async def splash(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            name="intake.html",
            request=request,
            context={
                "title": "Startup Intake",
                "workflow": workflow,
                "tracked_runs": len(run_items(None if workflow == "default" else workflow)),
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
                "title": "Workflow Binding",
                "workflow": workflow,
                "workflow_options": [
                    {"name": "agency", "label": "The Agency", "description": "Serial deep pipeline with a single-bound workflow path."},
                    {"name": "legion", "label": "The Legion", "description": "Parallel lane workflow with isolated run output and shared Basement support."},
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
                "title": "Workflow Binding",
                "workflow": workflow,
                "workflow_options": [
                    {"name": "agency", "label": "The Agency", "description": "Serial deep pipeline with a single-bound workflow path."},
                    {"name": "legion", "label": "The Legion", "description": "Parallel lane workflow with isolated run output and shared Basement support."},
                ],
            },
        )

    @app.get("/start", response_class=HTMLResponse)
    async def start_from_session(session_id: str, workflow_name: str) -> RedirectResponse:
        if workflow_name not in {"agency", "legion"}:
            raise HTTPException(status_code=400, detail="workflow_name must be agency or legion")
        session = IntakeSessionStore(repo_root).load(session_id)
        store = ArtifactStore(repo_root / "runs" / workflow_name)
        anchor_path = session_anchor_path(repo_root, session)
        run_id, run_dir = store.create_run(anchor_path, "intake", workflow_name)
        metadata = store.load_metadata(run_dir)
        metadata.status = "queued"
        metadata.stage = "intake_bound"
        metadata.intake_session_id = session.session_id
        metadata.source_type = session.source_type
        store.write_metadata(run_dir, metadata)
        prepare_basement(run_dir, workflow_name, session)
        return RedirectResponse(url=f"/runs/{workflow_name}/{run_id}", status_code=303)

    @app.get("/runs/{workflow_name}/{run_id}", response_class=HTMLResponse)
    async def run_detail_explicit(request: Request, workflow_name: str, run_id: str) -> HTMLResponse:
        run_dir, metadata = resolve_run(workflow_name, run_id)
        report_md = ""
        report_path = run_dir / "reports" / "report.md"
        if report_path.exists():
            report_md = report_path.read_text(encoding="utf-8")
        return templates.TemplateResponse(
            name="run_detail.html",
            request=request,
            context={
                "run": metadata,
                "report_md": report_md,
                "title": f"Run {run_id}",
                "workflow": workflow,
                "basement": basement_summary(run_dir),
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

    return app
