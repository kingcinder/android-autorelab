from __future__ import annotations

from pathlib import Path

from arelab.config import Settings
from arelab.runner import command_path


def _adjacent_analyze_headless(launcher: str | None) -> str | None:
    if not launcher:
        return None
    launcher_path = Path(launcher).resolve()
    support_dir = launcher_path.parent / "support"
    candidates = [
        support_dir / "analyzeHeadless",
        support_dir / "analyzeHeadless.bat",
        support_dir / "analyzeHeadless.sh",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def detect_tools(settings: Settings) -> dict[str, str | None]:
    repo = settings.repo_root
    overrides = settings.tool_overrides
    ghidra_launcher = overrides.get("ghidra") or command_path("ghidra")
    analyze_headless = _adjacent_analyze_headless(ghidra_launcher)
    tools = {
        "binwalk": overrides.get("binwalk") or command_path("binwalk"),
        "simg2img": overrides.get("simg2img") or command_path("simg2img"),
        "lpunpack": overrides.get("lpunpack") or command_path("lpunpack") or str(repo / "scripts" / "lpunpack.py"),
        "unpack_bootimg": overrides.get("unpack_bootimg") or command_path("unpack_bootimg.py") or str(repo / "scripts" / "unpack_bootimg.py"),
        "avbtool": overrides.get("avbtool") or command_path("avbtool") or str(repo / "scripts" / "avbtool.py"),
        "analyzeHeadless": overrides.get("analyzeHeadless") or analyze_headless,
        "file": overrides.get("file") or command_path("file"),
        "strings": overrides.get("strings") or command_path("strings"),
        "nm": overrides.get("nm") or command_path("nm"),
        "objdump": overrides.get("objdump") or command_path("objdump"),
        "readelf": command_path("readelf"),
        "gcc": overrides.get("gcc") or command_path("gcc"),
        "aarch64_gcc": overrides.get("aarch64_gcc") or command_path("aarch64-linux-gnu-gcc"),
    }
    return tools
