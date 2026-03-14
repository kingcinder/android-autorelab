from pathlib import Path

from arelab.config import Settings, _resolve_base_url
from arelab.workflows import load_workflow


def test_workflow_configs_present() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    agency = load_workflow(repo_root, "agency")
    legion = load_workflow(repo_root, "legion")
    assert agency.mode == "serial"
    assert legion.mode == "parallel"
    assert agency.router["models_max"] == 1
    assert legion.router["models_max"] == 3


def test_settings_runs_root_is_workflow_scoped() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    settings = Settings.load(repo_root, workflow="agency")
    assert settings.runs_root == repo_root / "runs" / "agency"


def test_resolve_base_url_prefers_env(monkeypatch) -> None:
    monkeypatch.setenv("ARELAB_OPENAI_BASE_URL", "http://127.0.0.1:9999/v1")
    assert _resolve_base_url({}) == "http://127.0.0.1:9999/v1"


def test_resolve_base_url_uses_router_config(monkeypatch) -> None:
    monkeypatch.delenv("ARELAB_OPENAI_BASE_URL", raising=False)
    assert _resolve_base_url({"base_url": "http://127.0.0.1:18081/v1"}) == "http://127.0.0.1:18081/v1"
