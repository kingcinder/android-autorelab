from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from arelab.runner import ToolRunner


class GhidraAnalyzer:
    def __init__(self, analyze_headless: str | None, repo_root: Path, runner: ToolRunner) -> None:
        self.analyze_headless = analyze_headless
        self.repo_root = repo_root
        self.runner = runner

    @property
    def available(self) -> bool:
        return bool(self.analyze_headless and Path(self.analyze_headless).exists())

    def analyze(self, binary_path: Path, out_dir: Path) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "error": "analyzeHeadless not found"}
        out_dir.mkdir(parents=True, exist_ok=True)
        project_root = out_dir / "project"
        project_root.mkdir(parents=True, exist_ok=True)
        facts_path = out_dir / "ghidra-facts.json"
        script_dir = self.repo_root / "ghidra_scripts"
        self.runner.run(
            "ghidra-headless",
            [
                self.analyze_headless or "",
                str(project_root),
                "arelab",
                "-import",
                str(binary_path),
                "-scriptPath",
                str(script_dir),
                "-postScript",
                "ExportFacts.java",
                str(facts_path),
                "-analysisTimeoutPerFile",
                "180",
                "-deleteProject",
            ],
            allow_failure=True,
            timeout=600,
        )
        if not facts_path.exists():
            return {"available": False, "error": "Ghidra facts were not produced"}
        with facts_path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
