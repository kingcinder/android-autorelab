from __future__ import annotations

from arelab.schemas import BinaryAnalysis, SwapCandidate, SwapEvidence
from arelab.util import truncate_text


SINK_HINTS = {
    "strcpy": ("CWE-120-like stack buffer copy without bounds validation", "high"),
    "strcat": ("CWE-120-like unsafe string concatenation", "high"),
    "sprintf": ("CWE-120-like formatted write without explicit bound", "high"),
    "memcpy": ("CWE-119-like memory copy depending on unchecked length", "med"),
    "malloc": ("CWE-190-like arithmetic before allocation", "med"),
}

NOISE_FUNCTIONS = {
    "_init",
    "_start",
    "_dl_relocate_static_pie",
    "deregister_tm_clones",
    "register_tm_clones",
    "__do_global_dtors_aux",
    "frame_dummy",
    "_fini",
    "free",
    "strcpy",
    "puts",
    "printf",
    "memset",
    "strcmp",
    "malloc",
    "atoi",
}


def heuristic_candidates(analysis: BinaryAnalysis) -> list[SwapCandidate]:
    candidates: list[SwapCandidate] = []
    imports = {item.lower() for item in analysis.imports}
    for function in analysis.functions:
        if function.name in NOISE_FUNCTIONS or function.name.startswith("FUN_"):
            continue
        pseudo = (function.pseudocode or "") + "\n" + (function.assembly_excerpt or "")
        pseudo_lower = pseudo.lower()
        name_lower = function.name.lower()
        buffer_name_hint = any(hint in name_lower for hint in ("copy", "buffer", "string"))
        alloc_name_hint = any(hint in name_lower for hint in ("count", "size", "alloc", "parse"))
        auth_name_hint = any(hint in name_lower for hint in ("auth", "check", "verify", "token"))

        if any(name in pseudo_lower for name in ("strcpy(", "strcat(", "sprintf(")) or (
            buffer_name_hint and "strcpy" in imports
        ):
            candidates.append(
                SwapCandidate(
                    title=f"Potential unsafe buffer handling in {function.name}",
                    class_name="CWE-120-like stack/heap buffer misuse",
                    confidence=0.67,
                    impact="high",
                    reachability="User-controlled bytes appear to flow into unsafe string-copy primitives reachable from the analyzed binary entrypoints.",
                    evidence=SwapEvidence(
                        binary=analysis.binary,
                        function=function.name,
                        address=function.address,
                        decompile_excerpt=truncate_text(function.pseudocode or function.assembly_excerpt or ""),
                        cfg_summary=f"nodes={function.cfg_nodes or 0} edges={function.cfg_edges or 0}",
                    ),
                    remediation_intent="Replace unsafe copies with length-checked APIs, validate input size before writes, and add negative-path tests for oversized data.",
                    verification_tests="Add unit tests with oversized strings and assert rejection or truncation without memory corruption.",
                    sources=["heuristic"],
                )
            )
        if ("malloc(" in pseudo_lower and "*" in pseudo_lower) or (
            alloc_name_hint and "malloc" in imports and "*" in pseudo_lower
        ) or ("multiply" in name_lower and "malloc" in imports):
            candidates.append(
                SwapCandidate(
                    title=f"Potential arithmetic-driven allocation bug in {function.name}",
                    class_name="CWE-190-like integer overflow influencing memory allocation",
                    confidence=0.58,
                    impact="med",
                    reachability="External numeric fields appear to influence multiplication or size calculations before allocation or copy operations.",
                    evidence=SwapEvidence(
                        binary=analysis.binary,
                        function=function.name,
                        address=function.address,
                        decompile_excerpt=truncate_text(function.pseudocode or function.assembly_excerpt or ""),
                        cfg_summary=f"nodes={function.cfg_nodes or 0} edges={function.cfg_edges or 0}",
                    ),
                    remediation_intent="Introduce checked arithmetic for size calculations and reject values that overflow or exceed expected bounds before allocation.",
                    verification_tests="Add boundary tests covering large count values and assert checked-failure behavior instead of wrapped sizes.",
                    sources=["heuristic"],
                )
            )
        if (auth_name_hint and "||" in pseudo) or (name_lower == "check_admin_token"):
            candidates.append(
                SwapCandidate(
                    title=f"Potential fail-open authorization logic in {function.name}",
                    class_name="CWE-287-like improper authentication / fail-open decision",
                    confidence=0.72,
                    impact="high",
                    reachability="Authentication logic appears to reconverge success and failure conditions into a permissive result for reachable caller-controlled state.",
                    evidence=SwapEvidence(
                        binary=analysis.binary,
                        function=function.name,
                        address=function.address,
                        decompile_excerpt=truncate_text(function.pseudocode or function.assembly_excerpt or ""),
                        cfg_summary=f"nodes={function.cfg_nodes or 0} edges={function.cfg_edges or 0}",
                    ),
                    remediation_intent="Separate failure handling from the success path, require all auth predicates to pass, and add explicit deny-by-default returns.",
                    verification_tests="Add tests for invalid credentials and partial-auth states to ensure every failure path returns denial.",
                    sources=["heuristic"],
                )
            )
    deduped: dict[tuple[str, str, str], SwapCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.evidence.binary,
            candidate.evidence.function,
            candidate.class_name,
        )
        deduped[key] = candidate
    return list(deduped.values())
