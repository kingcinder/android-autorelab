import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_router.py"
SPEC = importlib.util.spec_from_file_location("run_router_script", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
resolve_llama_bin = MODULE.resolve_llama_bin
default_llama_bin = MODULE.default_llama_bin


def test_resolve_llama_bin_preserves_bare_binary_name() -> None:
    resolved = resolve_llama_bin("llama-server")
    assert resolved.stem == "llama-server"
    assert "android-autorelab" not in str(resolved)


def test_resolve_llama_bin_expands_relative_path(tmp_path: Path) -> None:
    binary = tmp_path / "bin" / "llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    resolved = resolve_llama_bin(str(binary))
    assert resolved == binary.resolve()


def test_default_llama_bin_uses_tool_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARELAB_LLAMA_SERVER", raising=False)
    repo_root = tmp_path
    config_dir = repo_root / "config"
    workflows_dir = config_dir / "workflows"
    workflows_dir.mkdir(parents=True)
    (config_dir / "tools.yaml").write_text("overrides:\n  llama_server: /tmp/custom-llama-server\n", encoding="utf-8")
    (config_dir / "models.yaml").write_text("roles: {}\n", encoding="utf-8")
    (config_dir / "policies.yaml").write_text("{}\n", encoding="utf-8")
    (workflows_dir / "agency.yaml").write_text("router: {}\nroles: {}\npolicies: {}\n", encoding="utf-8")
    assert default_llama_bin(repo_root, "agency") == "/tmp/custom-llama-server"


def test_default_llama_bin_uses_local_override(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("ARELAB_LLAMA_SERVER", raising=False)
    repo_root = tmp_path
    config_dir = repo_root / "config"
    workflows_dir = config_dir / "workflows"
    workflows_dir.mkdir(parents=True)
    (config_dir / "tools.yaml").write_text("overrides: {}\n", encoding="utf-8")
    (config_dir / "models.yaml").write_text("roles: {}\n", encoding="utf-8")
    (config_dir / "policies.yaml").write_text("{}\n", encoding="utf-8")
    (config_dir / "local-overrides.yaml").write_text(
        "tools:\n  overrides:\n    llama_server: /tmp/local-llama-server\n",
        encoding="utf-8",
    )
    (workflows_dir / "agency.yaml").write_text("router: {}\nroles: {}\npolicies: {}\n", encoding="utf-8")
    assert default_llama_bin(repo_root, "agency") == "/tmp/local-llama-server"
