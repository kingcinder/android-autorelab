from __future__ import annotations

from pathlib import Path

from arelab.config import Settings
from arelab.runner import command_path


def detect_tools(settings: Settings) -> dict[str, str | None]:
    repo = settings.repo_root
    overrides = settings.tool_overrides
    ghidra_launcher = overrides.get("ghidra") or command_path("ghidra")
    analyze_headless = None
    if ghidra_launcher:
        launcher_path = Path(ghidra_launcher).resolve()
        candidate = launcher_path.parent.parent / "opt" / "ghidra-current" / "support" / "analyzeHeadless"
        if candidate.exists():
            analyze_headless = str(candidate)
    if not analyze_headless:
        fallback = Path.home() / ".local/opt/ghidra-current/support/analyzeHeadless"
        if fallback.exists():
            analyze_headless = str(fallback)
    tools = {
        "binwalk": overrides.get("binwalk") or command_path("binwalk"),
        "simg2img": overrides.get("simg2img") or command_path("simg2img"),
        "lpunpack": overrides.get("lpunpack") or command_path("lpunpack") or str(repo / "scripts" / "lpunpack.py"),
        "unpack_bootimg": overrides.get("unpack_bootimg") or command_path("unpack_bootimg.py") or str(repo / "scripts" / "unpack_bootimg.py"),
        "avbtool": overrides.get("avbtool") or command_path("avbtool") or str(repo / "scripts" / "avbtool.py"),
        "analyzeHeadless": overrides.get("analyzeHeadless") or analyze_headless,
        "file": command_path("file"),
        "strings": command_path("strings"),
        "nm": command_path("nm"),
        "objdump": command_path("objdump"),
        "readelf": command_path("readelf"),
        "gcc": command_path("gcc"),
        "aarch64_gcc": command_path("aarch64-linux-gnu-gcc"),
    }
    return tools
