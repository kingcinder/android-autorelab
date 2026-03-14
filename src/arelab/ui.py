from __future__ import annotations

import json
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from arelab.config import Settings


def create_app(repo_root: Path, workflow: str = "default") -> FastAPI:
    settings = Settings.load(repo_root, workflow=workflow)
    app = FastAPI(title="android-autorelab")
    templates = Jinja2Templates(directory=str(repo_root / "templates"))
    app.mount("/static", StaticFiles(directory=str(repo_root / "static")), name="static")

    def run_dirs() -> list[Path]:
        if not settings.runs_root.exists():
            return []
        return sorted([path for path in settings.runs_root.iterdir() if path.is_dir()], reverse=True)

    @app.get("/", response_class=HTMLResponse)
    @app.get("/runs", response_class=HTMLResponse)
    async def runs(request: Request) -> HTMLResponse:
        items = []
        for run_dir in run_dirs():
            meta_path = run_dir / "run.json"
            if meta_path.exists():
                items.append(json.loads(meta_path.read_text(encoding="utf-8")))
        return templates.TemplateResponse(
            name="runs.html",
            request=request,
            context={
                "runs": items,
                "title": "Runs",
                "workflow": workflow,
            },
        )

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    async def run_detail(request: Request, run_id: str) -> HTMLResponse:
        run_dir = settings.runs_root / run_id
        meta_path = run_dir / "run.json"
        if not meta_path.exists():
            raise HTTPException(status_code=404, detail="run not found")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
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
            },
        )

    @app.get("/runs/{run_id}/report", response_class=PlainTextResponse)
    async def report(run_id: str) -> PlainTextResponse:
        path = settings.runs_root / run_id / "reports" / "report.md"
        if not path.exists():
            raise HTTPException(status_code=404, detail="report not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/runs/{run_id}/artifacts", response_class=PlainTextResponse)
    async def artifacts(run_id: str) -> PlainTextResponse:
        path = settings.runs_root / run_id / "artifacts" / "manifest.json"
        if not path.exists():
            raise HTTPException(status_code=404, detail="manifest not found")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    return app
