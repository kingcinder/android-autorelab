from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import uvicorn

from arelab.pipeline import run_pipeline, status_for_run
from arelab.ui import create_app


def _program_workflow() -> str:
    name = Path(sys.argv[0]).name
    if "agencyctl" in name:
        return "agency"
    if "legionctl" in name:
        return "legion"
    return "default"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog=Path(sys.argv[0]).name)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--workflow", default=_program_workflow(), choices=["default", "agency", "legion"])
    sub = parser.add_subparsers(dest="command", required=True)

    run_cmd = sub.add_parser("run")
    run_cmd.add_argument("--input", required=True)
    run_cmd.add_argument("--output", default=None)
    run_cmd.add_argument("--profile", default="auto")

    demo_cmd = sub.add_parser("demo")
    demo_cmd.add_argument("--output", default=None)
    demo_cmd.add_argument("--profile", default="auto")

    status_cmd = sub.add_parser("status")
    status_cmd.add_argument("run_id")
    status_cmd.add_argument("--output", default=None)

    report_cmd = sub.add_parser("report")
    report_cmd.add_argument("run_id")
    report_cmd.add_argument("--format", choices=["md", "json"], default="md")
    report_cmd.add_argument("--output", default=None)

    serve_cmd = sub.add_parser("serve")
    serve_cmd.add_argument("--host", default="127.0.0.1")
    serve_cmd.add_argument("--port", type=int, default=8765)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    repo_root = Path(args.repo_root).resolve()
    if args.command == "run":
        run_id, run_dir = run_pipeline(
            repo_root=repo_root,
            input_path=Path(args.input).resolve(),
            output_root=Path(args.output).resolve() if args.output else None,
            profile=args.profile,
            workflow=args.workflow,
        )
        print(json.dumps({"run_id": run_id, "run_dir": str(run_dir)}, indent=2))
        return
    if args.command == "demo":
        run_id, run_dir = run_pipeline(
            repo_root=repo_root,
            input_path=None,
            output_root=Path(args.output).resolve() if args.output else None,
            profile=args.profile,
            workflow=args.workflow,
            demo=True,
        )
        print(json.dumps({"run_id": run_id, "run_dir": str(run_dir)}, indent=2))
        return
    if args.command == "status":
        meta = status_for_run(
            repo_root=repo_root,
            run_id=args.run_id,
            output_root=Path(args.output).resolve() if args.output else None,
            workflow=args.workflow,
        )
        print(meta.model_dump_json(indent=2))
        return
    if args.command == "report":
        base = Path(args.output).resolve() if args.output else repo_root / "runs" / args.workflow
        path = base / args.run_id / "reports" / f"report.{args.format}"
        print(path.read_text(encoding="utf-8"))
        return
    if args.command == "serve":
        uvicorn.run(create_app(repo_root, workflow=args.workflow), host=args.host, port=args.port)
