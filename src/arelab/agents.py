from __future__ import annotations

import json
from collections import defaultdict

from arelab.model_gateway import ModelGateway
from arelab.schemas import BinaryAnalysis, SwapCandidate


def _analysis_context(analysis: BinaryAnalysis) -> str:
    functions = []
    for function in analysis.functions[:12]:
        functions.append(
            {
                "name": function.name,
                "address": function.address,
                "pseudocode": function.pseudocode,
                "cfg_nodes": function.cfg_nodes,
                "cfg_edges": function.cfg_edges,
            }
        )
    return json.dumps(
        {
            "binary": analysis.binary,
            "imports": analysis.imports[:30],
            "heuristics": analysis.heuristics,
            "functions": functions,
        },
        indent=2,
    )


def _system_prompt_for(role: str) -> str:
    prompts = {
        "planner": (
            "You are a defensive planning agent for authorized reverse engineering. "
            "Return JSON only and focus on audit prioritization."
        ),
        "cleanup": (
            "You are a defensive remediation agent. Return JSON only with SWAP candidates that "
            "emphasize remediation intent and safe verification tests."
        ),
        "arbiter": (
            "You are a defensive severity arbiter. Return JSON only with SWAP candidates and "
            "normalize confidence and impact."
        ),
        "clerk": (
            "You are a defensive evidence clerk. Return JSON only and summarize consistent SWAP candidates."
        ),
    }
    return prompts.get(
        role,
        "You are a defensive vulnerability triage agent for authorized analysis. "
        "Do not output exploit steps. Return JSON only with swap_candidates.",
    )


def model_candidates(
    gateway: ModelGateway,
    analyses: list[BinaryAnalysis],
    roles: tuple[str, ...] = ("triage", "deep"),
) -> list[SwapCandidate]:
    candidates: list[SwapCandidate] = []
    for analysis in analyses:
        context = _analysis_context(analysis)
        for role in roles:
            try:
                payload = gateway.chat_json(
                    role=role,
                    system_prompt=_system_prompt_for(role),
                    user_prompt=(
                        "Review the binary facts below and return JSON with key swap_candidates. "
                        "Each candidate must contain title, class, confidence, impact, reachability, "
                        "evidence, remediation_intent, verification_tests.\n"
                        f"{context}"
                    ),
                    schema_name=f"{role}-{analysis.binary.rsplit('/', 1)[-1]}",
                    max_tokens=512,
                    timeout=120,
                )
            except Exception:  # noqa: BLE001
                payload = None
            if not payload:
                continue
            for item in payload.get("swap_candidates", []):
                try:
                    candidates.append(SwapCandidate.model_validate(item))
                except Exception:  # noqa: BLE001
                    continue
    return candidates


def merge_candidates(candidates: list[SwapCandidate]) -> list[SwapCandidate]:
    grouped: dict[tuple[str, str, str], list[SwapCandidate]] = defaultdict(list)
    for candidate in candidates:
        key = (
            candidate.evidence.binary,
            candidate.evidence.function,
            candidate.class_name,
        )
        grouped[key].append(candidate)
    merged: list[SwapCandidate] = []
    for idx, bucket in enumerate(grouped.values(), start=1):
        winner = max(bucket, key=lambda item: item.confidence).model_copy(deep=True)
        if len(bucket) > 1:
            winner.confidence = min(0.99, winner.confidence + 0.1 * (len(bucket) - 1))
            winner.sources = sorted({source for item in bucket for source in item.sources} | {"consensus"})
        else:
            winner.sources = sorted(set(winner.sources or ["single-pass"]))
        winner.id = f"SWAP-{idx:03d}"
        merged.append(winner)
    severity = {"critical": 4, "high": 3, "med": 2, "low": 1}
    merged.sort(key=lambda item: (severity[item.impact], item.confidence), reverse=True)
    return merged
