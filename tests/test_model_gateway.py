from __future__ import annotations

from pathlib import Path

from arelab.config import Settings
from arelab.model_gateway import ModelGateway


def _settings_fixture(tmp_path: Path) -> Settings:
    repo_root = tmp_path / "repo"
    config_dir = repo_root / "config"
    workflows_dir = config_dir / "workflows"
    workflows_dir.mkdir(parents=True)
    (config_dir / "models.yaml").write_text("roles: {}\n", encoding="utf-8")
    (config_dir / "tools.yaml").write_text("overrides: {}\n", encoding="utf-8")
    (config_dir / "policies.yaml").write_text("{}\n", encoding="utf-8")
    (workflows_dir / "agency.yaml").write_text(
        "\n".join(
            [
                "router:",
                "  base_url: http://127.0.0.1:18081/v1",
                "roles:",
                "  planner: qwen2.5-coder-1.5b-instruct-q6_k",
                "pipeline: {}",
                "policies: {}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return Settings.load(repo_root, workflow="agency")


def test_available_models_ensures_router_ready(tmp_path: Path, monkeypatch) -> None:
    settings = _settings_fixture(tmp_path)
    prompts_dir = tmp_path / "prompts"
    calls: list[str] = []

    def fake_ensure(current: Settings, *, timeout: int = 30) -> None:
        assert current.workflow == "agency"
        calls.append("ensure")

    def fake_request(self: ModelGateway, path: str, payload=None, *, timeout: int = 30):
        assert path == "/models"
        return {"data": [{"id": "qwen2.5-coder-1.5b-instruct-q6_k"}]}

    monkeypatch.setattr("arelab.model_gateway.ensure_router_ready", fake_ensure)
    monkeypatch.setattr(ModelGateway, "_request", fake_request)

    gateway = ModelGateway(settings, prompts_dir)
    assert gateway.available_models() == ["qwen2.5-coder-1.5b-instruct-q6_k"]
    assert calls == ["ensure"]


def test_chat_text_ensures_router_ready_and_logs_exchange(tmp_path: Path, monkeypatch) -> None:
    settings = _settings_fixture(tmp_path)
    prompts_dir = tmp_path / "prompts"
    calls: list[str] = []
    router_calls: list[tuple[str, str]] = []

    def fake_ensure(current: Settings, *, timeout: int = 30) -> None:
        assert current.workflow == "agency"
        calls.append("ensure")

    class FakeRouterClient:
        def __init__(self, current: Settings) -> None:
            assert current.workflow == "agency"

        def active_models(self) -> list[str]:
            return []

        def loaded_models(self) -> list[str]:
            return []

        def unload_model(self, model: str, timeout: int = 240):
            router_calls.append(("unload", model))
            return {"success": True}

        def wait_for_model_state(self, model: str, *, expected, timeout: int = 180, settle_seconds: float = 1.0):
            router_calls.append(("wait", model))
            return "loaded"

        def load_model(self, model: str, timeout: int = 240):
            router_calls.append(("load", model))
            return {"success": True}

        def warm_model(self, model: str, timeout: int = 180) -> None:
            router_calls.append(("warm", model))

    def fake_request(self: ModelGateway, path: str, payload=None, *, timeout: int = 30):
        assert path == "/chat/completions"
        return {"choices": [{"message": {"content": "Ready."}}]}

    monkeypatch.setattr("arelab.model_gateway.ensure_router_ready", fake_ensure)
    monkeypatch.setattr("arelab.model_gateway.RouterClient", FakeRouterClient)
    monkeypatch.setattr(ModelGateway, "_request", fake_request)

    gateway = ModelGateway(settings, prompts_dir)
    response = gateway.chat_text(prompt="Explain the current stage.")

    assert response["response"] == "Ready."
    assert calls == ["ensure", "ensure"]
    assert ("load", "qwen2.5-coder-1.5b-instruct-q6_k") in router_calls
    assert ("warm", "qwen2.5-coder-1.5b-instruct-q6_k") in router_calls
    assert gateway.console_log_path.exists()
