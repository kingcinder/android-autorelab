from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from arelab.config import load_yaml


@dataclass(slots=True)
class WorkflowSpec:
    name: str
    mode: str
    description: str
    router: dict[str, Any]
    roles: dict[str, str]
    pipeline: dict[str, Any]
    policies: dict[str, Any]


def load_workflow(repo_root: Path, workflow: str) -> WorkflowSpec:
    payload = load_yaml(repo_root / "config" / "workflows" / f"{workflow}.yaml")
    if not payload:
        if workflow != "default":
            raise FileNotFoundError(f"Missing workflow config for {workflow}")
        payload = {
            "name": "default",
            "mode": "serial",
            "description": "Default arelab workflow",
            "router": {},
            "roles": {},
            "pipeline": {},
            "policies": {},
        }
    return WorkflowSpec(
        name=payload.get("name", workflow),
        mode=payload.get("mode", "serial"),
        description=payload.get("description", ""),
        router=payload.get("router", {}),
        roles=payload.get("roles", {}),
        pipeline=payload.get("pipeline", {}),
        policies=payload.get("policies", {}),
    )
