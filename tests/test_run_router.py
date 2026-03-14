import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "run_router.py"
SPEC = importlib.util.spec_from_file_location("run_router_script", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
resolve_llama_bin = MODULE.resolve_llama_bin


def test_resolve_llama_bin_preserves_bare_binary_name() -> None:
    resolved = resolve_llama_bin("llama-server")
    assert resolved.name == "llama-server"
    assert "android-autorelab" not in str(resolved)


def test_resolve_llama_bin_expands_relative_path(tmp_path: Path) -> None:
    binary = tmp_path / "bin" / "llama-server"
    binary.parent.mkdir(parents=True)
    binary.write_text("", encoding="utf-8")
    resolved = resolve_llama_bin(str(binary))
    assert resolved == binary.resolve()
