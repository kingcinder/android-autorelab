from __future__ import annotations

import json
from pathlib import Path

from arelab.cfg import extract_cfg
from arelab.ghidra import GhidraAnalyzer
from arelab.heuristics import heuristic_candidates
from arelab.runner import ToolRunner
from arelab.schemas import ArtifactManifest, BinaryAnalysis, FunctionFact
from arelab.util import json_dump, sha256_file


def _binary_candidates(manifest: ArtifactManifest) -> list[Path]:
    candidates: list[Path] = []
    for node in manifest.nodes:
        path = Path(node.path)
        if not path.is_file():
            continue
        candidates.append(path)
    seen: set[Path] = set()
    result: list[Path] = []
    for path in candidates:
        if path not in seen:
            seen.add(path)
            result.append(path)
    return result


def _read_output(runner: ToolRunner, label: str, command: list[str]) -> str:
    execution = runner.run(label, command, allow_failure=True)
    return Path(execution.stdout_path).read_text(encoding="utf-8", errors="replace")


def analyze_manifest(
    manifest: ArtifactManifest,
    artifacts_dir: Path,
    tools: dict[str, str | None],
    runner: ToolRunner,
    ghidra: GhidraAnalyzer,
) -> list[BinaryAnalysis]:
    analyses: list[BinaryAnalysis] = []
    for binary_path in _binary_candidates(manifest):
        file_output = ""
        if tools.get("file"):
            file_output = _read_output(runner, "file", [tools["file"], str(binary_path)])
        if not any(fmt in file_output for fmt in ("ELF", "PE32", "Mach-O")):
            continue
        imports = []
        if tools.get("objdump"):
            objdump_out = _read_output(runner, "objdump-dynamic", [tools["objdump"], "-T", str(binary_path)])
            for line in objdump_out.splitlines():
                if "UND" in line:
                    parts = line.split()
                    if parts:
                        imports.append(parts[-1])
        strings = []
        if tools.get("strings"):
            strings_out = _read_output(runner, "strings", [tools["strings"], "-a", "-n", "4", str(binary_path)])
            strings = strings_out.splitlines()[:200]
        nm_functions = []
        if tools.get("nm"):
            nm_out = _read_output(runner, "nm", [tools["nm"], "-n", "--defined-only", str(binary_path)])
            nm_functions = [line for line in nm_out.splitlines() if " T " in line or " t " in line]
        ghidra_out = ghidra.analyze(binary_path, artifacts_dir / binary_path.stem / "ghidra")
        cfg_out = extract_cfg(binary_path)
        functions: list[FunctionFact] = []
        if ghidra_out.get("functions"):
            cfg_functions = cfg_out.get("functions", {})
            for item in ghidra_out["functions"][:64]:
                cfg_meta = cfg_functions.get(item["name"], {})
                functions.append(
                    FunctionFact(
                        name=item["name"],
                        address=item["address"],
                        pseudocode=item.get("pseudocode"),
                        assembly_excerpt=item.get("assembly_excerpt"),
                        xref_count=item.get("xref_count"),
                        cfg_nodes=cfg_meta.get("nodes"),
                        cfg_edges=cfg_meta.get("edges"),
                    )
                )
        else:
            for line in nm_functions[:64]:
                parts = line.split()
                if len(parts) >= 3:
                    functions.append(FunctionFact(name=parts[2], address=f"0x{parts[0]}"))
        analysis = BinaryAnalysis(
            binary=str(binary_path),
            sha256=sha256_file(binary_path),
            file_output=file_output.strip(),
            imports=sorted(set(imports)),
            strings=strings,
            functions=functions,
            cfg_summary=cfg_out,
            ghidra_summary=ghidra_out,
        )
        analysis.heuristics = [item.model_dump(by_alias=True) for item in heuristic_candidates(analysis)]
        analyses.append(analysis)
        json_dump(
            artifacts_dir / binary_path.stem / "analysis.json",
            json.loads(analysis.model_dump_json(by_alias=True)),
        )
    return analyses
