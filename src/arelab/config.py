from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in {path}")
    return payload


def merge_yaml(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        if isinstance(current, dict) and isinstance(value, dict):
            merged[key] = merge_yaml(current, value)
        else:
            merged[key] = value
    return merged


def _expand_pathlike(value: str | None, repo_root: Path) -> str | None:
    if not value:
        return value
    expanded = os.path.expandvars(os.path.expanduser(str(value)))
    if os.path.isabs(expanded):
        return expanded
    return str((repo_root / expanded).resolve())


def _probe_base_url(base_url: str, timeout: float = 1.5) -> bool:
    models_url = f"{base_url.rstrip('/')}/models"
    try:
        with urllib.request.urlopen(models_url, timeout=timeout) as response:
            return response.status == 200
    except (OSError, ValueError, urllib.error.URLError):
        return False


def _resolve_base_url(router: dict[str, Any]) -> str:
    env_base_url = os.environ.get("ARELAB_OPENAI_BASE_URL")
    if env_base_url:
        return env_base_url.rstrip("/")

    router_base_url = str(router.get("base_url", "")).rstrip("/")
    if router_base_url:
        return router_base_url

    for candidate in ("http://127.0.0.1:10000/v1", "http://127.0.0.1:8000/v1"):
        if _probe_base_url(candidate):
            return candidate
    return "http://127.0.0.1:10000/v1"


@dataclass(slots=True)
class Settings:
    repo_root: Path
    runs_root: Path
    workflow: str
    openai_base_url: str
    openai_api_key: str
    model_pins: dict[str, str]
    tool_overrides: dict[str, str]
    policies: dict[str, Any]
    workflow_config: dict[str, Any]

    @classmethod
    def load(cls, repo_root: Path, workflow: str = "default") -> "Settings":
        config_root = repo_root / "config"
        local_overrides = load_yaml(config_root / "local-overrides.yaml")
        models = merge_yaml(load_yaml(config_root / "models.yaml"), local_overrides.get("models", {}))
        tools = merge_yaml(load_yaml(config_root / "tools.yaml"), local_overrides.get("tools", {}))
        policies = merge_yaml(load_yaml(config_root / "policies.yaml"), local_overrides.get("policies", {}))
        workflow_overrides = (local_overrides.get("workflows", {}) or {}).get(workflow, {})
        workflow_config = merge_yaml(load_yaml(config_root / "workflows" / f"{workflow}.yaml"), workflow_overrides)
        tool_overrides = {
            key: _expand_pathlike(value, repo_root) if isinstance(value, str) else value
            for key, value in tools.get("overrides", {}).items()
        }
        router = dict(workflow_config.get("router", {}))
        env_models_dir = os.environ.get("ARELAB_MODELS_DIR")
        if env_models_dir:
            router["models_dir"] = _expand_pathlike(env_models_dir, repo_root)
        elif isinstance(router.get("models_dir"), str):
            router["models_dir"] = _expand_pathlike(router["models_dir"], repo_root)
        if router:
            workflow_config["router"] = router
        workflow_roles = workflow_config.get("roles", {})
        workflow_policies = workflow_config.get("policies", {})
        base_url = _resolve_base_url(router)
        api_key = os.environ.get("ARELAB_OPENAI_API_KEY", "none")
        return cls(
            repo_root=repo_root,
            runs_root=repo_root / "runs" / workflow,
            workflow=workflow,
            openai_base_url=base_url.rstrip("/"),
            openai_api_key=api_key,
            model_pins={**models.get("roles", {}), **workflow_roles},
            tool_overrides=tool_overrides,
            policies={**policies, **workflow_policies},
            workflow_config=workflow_config,
        )
