from __future__ import annotations

from pathlib import Path
from typing import Any


def extract_cfg(binary_path: Path) -> dict[str, Any]:
    try:
        import angr  # type: ignore
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": str(exc), "functions": {}}

    project = angr.Project(str(binary_path), auto_load_libs=False)
    cfg = project.analyses.CFGFast(normalize=True)
    function_summaries: dict[str, Any] = {}
    for addr, function in cfg.kb.functions.items():
        if function.is_plt:
            continue
        blocks = list(function.blocks)
        transition_graph = function.transition_graph
        function_summaries[function.name] = {
            "address": hex(addr),
            "nodes": len(blocks),
            "edges": int(transition_graph.number_of_edges()),
            "block_addrs": [hex(block.addr) for block in blocks[:32]],
        }
    return {
        "available": True,
        "function_count": len(function_summaries),
        "functions": function_summaries,
    }
